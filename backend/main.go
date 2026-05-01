package main

import (
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	addr := envOrDefault("HTTP_ADDR", ":8080")
	cameraURL := envOrDefault("PI_CAMERA_URL", "http://localhost:8081/stream")

	state := NewServerState()
	hub := NewHub()
	go hub.Run()

	router := NewRouter(hub, state, cameraURL)

	server := &http.Server{
		Addr:              addr,
		Handler:           router,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	log.Printf("backend listening on %s", addr)
	if err := server.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
