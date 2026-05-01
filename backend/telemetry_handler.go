package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"
)

func broadcastTyped(hub *Hub, msgType string, data interface{}) {
	payload, err := json.Marshal(data)
	if err != nil {
		return
	}
	wire, err := json.Marshal(WSMessage{Type: msgType, Data: payload})
	if err != nil {
		return
	}
	hub.broadcast <- wire
}

func handleTelemetry(state *ServerState, hub *Hub) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var env TelemetryEnvelope
		if err := json.NewDecoder(r.Body).Decode(&env); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}

		if env.Telemetry != nil {
			state.UpdateTelemetry(*env.Telemetry)
			broadcastTyped(hub, "telemetry", env.Telemetry)
		}
		if len(env.Path) > 0 {
			state.UpdatePath(env.Path)
			broadcastTyped(hub, "path", env.Path)
		}
		if env.Victim != nil {
			state.AddVictim(*env.Victim)
			broadcastTyped(hub, "victim", env.Victim)
		}
		if len(env.Victims) > 0 {
			state.ReplaceVictims(env.Victims)
			broadcastTyped(hub, "victims", env.Victims)
		}
		if env.Alert != nil {
			state.AddAlert(*env.Alert)
			broadcastTyped(hub, "alert", env.Alert)
		}
		if len(env.Alerts) > 0 {
			for _, a := range env.Alerts {
				state.AddAlert(a)
			}
			broadcastTyped(hub, "alerts", env.Alerts)
		}
		if env.Log != nil {
			state.AddLog(*env.Log)
			broadcastTyped(hub, "log", env.Log)
		}
		if len(env.Logs) > 0 {
			for _, l := range env.Logs {
				state.AddLog(l)
			}
			broadcastTyped(hub, "logs", env.Logs)
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("{\"ok\":true}"))
	}
}

func handleCommand(state *ServerState, hub *Hub) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var cmd CommandRequest
		if err := json.NewDecoder(r.Body).Decode(&cmd); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		cmd.Command = strings.ToUpper(strings.TrimSpace(cmd.Command))
		if !isValidCommand(cmd.Command) {
			http.Error(w, "invalid command", http.StatusBadRequest)
			return
		}

		state.SetLastCommand(cmd.Command)
		broadcastTyped(hub, "command", cmd)

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("{\"ok\":true}"))
	}
}

func handleState(state *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		snap := state.Snapshot()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(snap)
	}
}

func isValidCommand(c string) bool {
	if len(c) != 1 {
		return false
	}
	switch c {
	case "F", "B", "L", "R", "S":
		return true
	default:
		return false
	}
}

func newAlert(level, message string) Alert {
	return Alert{
		Level:       level,
		Message:     message,
		TimestampMs: time.Now().UnixMilli(),
	}
}
