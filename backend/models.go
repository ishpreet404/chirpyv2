package main

import (
	"encoding/json"
	"sync"
	"time"
)

type Telemetry struct {
	TimestampMs int64   `json:"timestampMs"`
	RPM         float64 `json:"rpm"`
	DistCm      int     `json:"distCm"`
	AccelY      float64 `json:"accelY"`
	GyroZ       float64 `json:"gyroZ"`
	X           float64 `json:"x"`
	Y           float64 `json:"y"`
	Heading     float64 `json:"heading"`
	DistLapCm   float64 `json:"distLapCm"`
	DistTotalCm float64 `json:"distTotalCm"`
	BatteryV    float64 `json:"batteryV"`
	Obstacle    bool    `json:"obstacle"`
	State       string  `json:"state"`
	Flags       string  `json:"flags"`
	Lat         float64 `json:"lat"`
	Lon         float64 `json:"lon"`
	GPSFix      bool    `json:"gpsFix"`
	GPSHdop     float64 `json:"gpsHdop"`
}

type PathPoint struct {
	X           float64 `json:"x"`
	Y           float64 `json:"y"`
	Heading     float64 `json:"heading"`
	TimestampMs int64   `json:"timestampMs"`
}

type Victim struct {
	ID          string  `json:"id"`
	X           float64 `json:"x"`
	Y           float64 `json:"y"`
	Lat         float64 `json:"lat"`
	Lon         float64 `json:"lon"`
	Confidence  float64 `json:"confidence"`
	DetectedAt  int64   `json:"detectedAt"`
	Source      string  `json:"source"`
	Notes       string  `json:"notes"`
}

type Alert struct {
	Level       string `json:"level"`
	Message     string `json:"message"`
	TimestampMs int64  `json:"timestampMs"`
}

type LogEntry struct {
	Level       string `json:"level"`
	Message     string `json:"message"`
	TimestampMs int64  `json:"timestampMs"`
}

type CommandRequest struct {
	Command string `json:"command"`
}

type TelemetryEnvelope struct {
	Telemetry *Telemetry  `json:"telemetry"`
	Path      []PathPoint `json:"path"`
	Victims   []Victim    `json:"victims"`
	Victim    *Victim     `json:"victim"`
	Alerts    []Alert     `json:"alerts"`
	Alert     *Alert      `json:"alert"`
	Logs      []LogEntry  `json:"logs"`
	Log       *LogEntry   `json:"log"`
}

type WSMessage struct {
	Type string          `json:"type"`
	Data json.RawMessage `json:"data"`
}

type ServerState struct {
	mu          sync.RWMutex
	Telemetry   Telemetry
	Path        []PathPoint
	Victims     []Victim
	Alerts      []Alert
	Logs        []LogEntry
	LastCommand string
	UpdatedAt   time.Time
}

type StateSnapshot struct {
	Telemetry   Telemetry  `json:"telemetry"`
	Path        []PathPoint `json:"path"`
	Victims     []Victim   `json:"victims"`
	Alerts      []Alert    `json:"alerts"`
	Logs        []LogEntry `json:"logs"`
	LastCommand string     `json:"lastCommand"`
	UpdatedAt   time.Time  `json:"updatedAt"`
}

func NewServerState() *ServerState {
	return &ServerState{
		Telemetry: Telemetry{},
		Path:      []PathPoint{},
		Victims:   []Victim{},
		Alerts:    []Alert{},
		Logs:      []LogEntry{},
		UpdatedAt: time.Now(),
	}
}

func (s *ServerState) Snapshot() StateSnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()

	path := append([]PathPoint(nil), s.Path...)
	victims := append([]Victim(nil), s.Victims...)
	alerts := append([]Alert(nil), s.Alerts...)
	logs := append([]LogEntry(nil), s.Logs...)

	return StateSnapshot{
		Telemetry:   s.Telemetry,
		Path:        path,
		Victims:     victims,
		Alerts:      alerts,
		Logs:        logs,
		LastCommand: s.LastCommand,
		UpdatedAt:   s.UpdatedAt,
	}
}

func (s *ServerState) UpdateTelemetry(t Telemetry) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Telemetry = t
	s.UpdatedAt = time.Now()
}

func (s *ServerState) UpdatePath(points []PathPoint) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(points) > 5000 {
		points = points[len(points)-5000:]
	}
	s.Path = append([]PathPoint(nil), points...)
	s.UpdatedAt = time.Now()
}

func (s *ServerState) AddVictim(v Victim) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Victims = append(s.Victims, v)
	if len(s.Victims) > 500 {
		s.Victims = s.Victims[len(s.Victims)-500:]
	}
	s.UpdatedAt = time.Now()
}

func (s *ServerState) ReplaceVictims(v []Victim) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(v) > 500 {
		v = v[len(v)-500:]
	}
	s.Victims = append([]Victim(nil), v...)
	s.UpdatedAt = time.Now()
}

func (s *ServerState) AddAlert(a Alert) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Alerts = append(s.Alerts, a)
	if len(s.Alerts) > 200 {
		s.Alerts = s.Alerts[len(s.Alerts)-200:]
	}
	s.UpdatedAt = time.Now()
}

func (s *ServerState) AddLog(l LogEntry) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Logs = append(s.Logs, l)
	if len(s.Logs) > 500 {
		s.Logs = s.Logs[len(s.Logs)-500:]
	}
	s.UpdatedAt = time.Now()
}

func (s *ServerState) SetLastCommand(cmd string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.LastCommand = cmd
	s.UpdatedAt = time.Now()
}
