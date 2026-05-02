import { useCallback, useEffect, useRef, useState } from 'react';

const DEFAULT_COMMANDS = ['F', 'B', 'L', 'R', 'S'];

function buildWsUrl() {
  if (process.env.REACT_APP_WS_URL) return process.env.REACT_APP_WS_URL;
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.hostname}:8000/ws/dashboard`;
}

function buildHttpBase(wsUrl) {
  return wsUrl.replace(/^ws/, 'http').replace(/\/ws\/dashboard$/, '');
}

export function useRoverWebSocket() {
  const wsRef = useRef(null);
  const wsUrlRef = useRef(buildWsUrl());
  const httpBaseRef = useRef(buildHttpBase(wsUrlRef.current));

  const [connected, setConnected] = useState(false);
  const [telemetry, setTelemetry] = useState(null);
  const [pathData, setPathData] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState({
    pi_connected: false,
    mission_active: false,
    rover_state: 'STP',
    auto_mode: false,
    obstacle_active: false,
    victim_count: 0,
    capabilities: { commands: DEFAULT_COMMANDS },
  });

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer = null;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(wsUrlRef.current);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, 1500);
        }
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (evt) => {
        let msg;
        try {
          msg = JSON.parse(evt.data);
        } catch (e) {
          return;
        }

        if (msg.type === 'init') {
          setTelemetry(msg.telemetry || null);
          setPathData(msg.path || null);
          setAlerts(msg.alerts || []);
          if (msg.status) {
            setStatus(prev => ({
              ...prev,
              ...msg.status,
              capabilities: msg.status.capabilities || prev.capabilities,
            }));
          }
          return;
        }

        if (msg.type === 'telemetry') {
          setTelemetry(msg.telemetry || null);
          if (msg.path) setPathData(msg.path);
          return;
        }

        if (msg.type === 'event') {
          if (msg.alert) {
            setAlerts(prev => [msg.alert, ...prev].slice(0, 200));
          }
          return;
        }

        if (msg.type === 'victim') {
          if (msg.alert) {
            setAlerts(prev => [msg.alert, ...prev].slice(0, 200));
          }
          setStatus(prev => ({
            ...prev,
            victim_count: msg.count ?? prev.victim_count,
          }));
          return;
        }

        if (msg.type === 'cmd_sent') {
          if (msg.auto_mode != null) {
            setStatus(prev => ({ ...prev, auto_mode: msg.auto_mode }));
          }
          return;
        }

        if (msg.type === 'heartbeat' && msg.status) {
          setStatus(prev => ({
            ...prev,
            ...msg.status,
            capabilities: msg.status.capabilities || prev.capabilities,
          }));
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const sendCommand = useCallback((cmd) => {
    const clean = (cmd || '').toUpperCase();
    const allowed = status?.capabilities?.commands || DEFAULT_COMMANDS;
    if (!allowed.includes(clean)) return;

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'command', command: clean }));
      return;
    }

    fetch(`${httpBaseRef.current}/api/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: clean }),
    }).catch(() => {});
  }, [status]);

  return { connected, telemetry, pathData, alerts, status, sendCommand };
}
