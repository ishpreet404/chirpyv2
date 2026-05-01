package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/gorilla/websocket"
)

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = (pongWait * 9) / 10
	maxMessageSize = 8192
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

type Hub struct {
	clients    map[*Client]bool
	broadcast  chan []byte
	register   chan *Client
	unregister chan *Client
}

type Client struct {
	hub   *Hub
	conn  *websocket.Conn
	send  chan []byte
	state *ServerState
}

func NewHub() *Hub {
	return &Hub{
		clients:    make(map[*Client]bool),
		broadcast:  make(chan []byte, 256),
		register:   make(chan *Client),
		unregister: make(chan *Client),
	}
}

func (h *Hub) Run() {
	for {
		select {
		case client := <-h.register:
			h.clients[client] = true
		case client := <-h.unregister:
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
		case message := <-h.broadcast:
			for client := range h.clients {
				select {
				case client.send <- message:
				default:
					close(client.send)
					delete(h.clients, client)
				}
			}
		}
	}
}

func (h *Hub) BroadcastJSON(msgType string, data interface{}) {
	payload, err := json.Marshal(data)
	if err != nil {
		return
	}
	msg := WSMessage{Type: msgType, Data: payload}
	wire, err := json.Marshal(msg)
	if err != nil {
		return
	}
	h.broadcast <- wire
}

func serveWS(hub *Hub, state *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("ws upgrade error: %v", err)
			return
		}
		client := &Client{hub: hub, conn: conn, send: make(chan []byte, 256), state: state}
		client.hub.register <- client

		go client.writePump()
		go client.readPump()
	}
}

func (c *Client) readPump() {
	defer func() {
		c.hub.unregister <- c
		c.conn.Close()
	}()
	c.conn.SetReadLimit(maxMessageSize)
	c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			break
		}

		var envelope WSMessage
		if err := json.Unmarshal(message, &envelope); err != nil {
			continue
		}
		switch envelope.Type {
		case "telemetry":
			var t Telemetry
			if err := json.Unmarshal(envelope.Data, &t); err == nil {
				c.state.UpdateTelemetry(t)
				c.hub.broadcast <- message
			}
		case "path":
			var p []PathPoint
			if err := json.Unmarshal(envelope.Data, &p); err == nil {
				c.state.UpdatePath(p)
				c.hub.broadcast <- message
			}
		case "victims":
			var v []Victim
			if err := json.Unmarshal(envelope.Data, &v); err == nil {
				c.state.ReplaceVictims(v)
				c.hub.broadcast <- message
			}
		case "victim":
			var v Victim
			if err := json.Unmarshal(envelope.Data, &v); err == nil {
				c.state.AddVictim(v)
				c.hub.broadcast <- message
			}
		case "alert":
			var a Alert
			if err := json.Unmarshal(envelope.Data, &a); err == nil {
				c.state.AddAlert(a)
				c.hub.broadcast <- message
			}
		case "log":
			var l LogEntry
			if err := json.Unmarshal(envelope.Data, &l); err == nil {
				c.state.AddLog(l)
				c.hub.broadcast <- message
			}
		case "command":
			var cmd CommandRequest
			if err := json.Unmarshal(envelope.Data, &cmd); err == nil {
				c.state.SetLastCommand(cmd.Command)
				c.hub.broadcast <- message
			}
		default:
			continue
		}
	}
}

func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.send:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := c.conn.WriteMessage(websocket.TextMessage, message); err != nil {
				return
			}
		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}
