import React, { useEffect, useMemo, useRef, useState } from "react";
import AlertsBar from "./components/AlertsBar.jsx";
import MapView from "./components/MapView.jsx";
import CameraFeed from "./components/CameraFeed.jsx";
import TelemetryPanel from "./components/TelemetryPanel.jsx";
import LogsPanel from "./components/LogsPanel.jsx";
import Controls from "./components/Controls.jsx";

const initialTelemetry = {
  timestampMs: 0,
  rpm: 0,
  distCm: 0,
  accelY: 0,
  gyroZ: 0,
  x: 0,
  y: 0,
  heading: 0,
  distLapCm: 0,
  distTotalCm: 0,
  batteryV: 0,
  obstacle: false,
  state: "STP",
  flags: "OK",
  lat: 0,
  lon: 0,
  gpsFix: false,
  gpsHdop: 0
};

const historyLimit = 120;

export default function App() {
  const [telemetry, setTelemetry] = useState(initialTelemetry);
  const [path, setPath] = useState([]);
  const [victims, setVictims] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [logs, setLogs] = useState([]);
  const [history, setHistory] = useState({ battery: [], rpm: [], heading: [] });
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);

  const wsUrl = useMemo(() => {
    const envUrl = import.meta?.env?.VITE_WS_URL;
    if (envUrl) return envUrl;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/ws`;
  }, []);

  useEffect(() => {
    fetch("/api/state")
      .then((res) => res.json())
      .then((data) => {
        if (data?.telemetry) setTelemetry(data.telemetry);
        if (Array.isArray(data?.path)) setPath(data.path);
        if (Array.isArray(data?.victims)) setVictims(data.victims);
        if (Array.isArray(data?.alerts)) setAlerts(data.alerts);
        if (Array.isArray(data?.logs)) setLogs(data.logs);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onerror = () => setWsConnected(false);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (!msg?.type) return;

        switch (msg.type) {
          case "telemetry":
            setTelemetry(msg.data);
            break;
          case "path":
            setPath(Array.isArray(msg.data) ? msg.data : msg.data?.points || []);
            break;
          case "victims":
            setVictims(Array.isArray(msg.data) ? msg.data : []);
            break;
          case "victim":
            setVictims((prev) => {
              const exists = prev.some((v) => v.id && v.id === msg.data?.id);
              return exists ? prev : [msg.data, ...prev].slice(0, 200);
            });
            break;
          case "alerts":
            setAlerts(Array.isArray(msg.data) ? msg.data : []);
            break;
          case "alert":
            setAlerts((prev) => [msg.data, ...prev].slice(0, 10));
            break;
          case "log":
            setLogs((prev) => [msg.data, ...prev].slice(0, 200));
            break;
          case "logs":
            setLogs(Array.isArray(msg.data) ? msg.data : []);
            break;
          default:
            break;
        }
      } catch {
        // ignore malformed
      }
    };

    return () => {
      ws.close();
    };
  }, [wsUrl]);

  useEffect(() => {
    if (!telemetry) return;
    setHistory((prev) => {
      const next = {
        battery: [...prev.battery, telemetry.batteryV || 0],
        rpm: [...prev.rpm, telemetry.rpm || 0],
        heading: [...prev.heading, telemetry.heading || 0]
      };
      return {
        battery: next.battery.slice(-historyLimit),
        rpm: next.rpm.slice(-historyLimit),
        heading: next.heading.slice(-historyLimit)
      };
    });
  }, [telemetry]);

  const sendCommand = async (cmd) => {
    try {
      await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd })
      });
    } catch {
      // ignore
    }
  };

  const robot = useMemo(
    () => ({ x: telemetry.x || 0, y: telemetry.y || 0, heading: telemetry.heading || 0 }),
    [telemetry]
  );

  return (
    <div className="app">
      <AlertsBar alerts={alerts} wsConnected={wsConnected} telemetry={telemetry} />

      <div className="main-grid">
        <MapView path={path} victims={victims} robot={robot} />
        <div className="right-stack">
          <CameraFeed streamUrl="/camera/stream" />
          <Controls onCommand={sendCommand} />
        </div>
      </div>

      <div className="bottom-grid">
        <TelemetryPanel telemetry={telemetry} history={history} />
        <LogsPanel logs={logs} />
      </div>
    </div>
  );
}
