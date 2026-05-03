import { useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_COMMANDS = ["F", "B", "L", "R", "S"];

function buildWsBase() {
	if (process.env.REACT_APP_WS_URL) return process.env.REACT_APP_WS_URL;
	if (process.env.REACT_APP_API_URL) {
		return process.env.REACT_APP_API_URL.replace(/^http/, "ws");
	}
	const proto = window.location.protocol === "https:" ? "wss" : "ws";
	return `${proto}://${window.location.hostname}:8000`;
}

function buildHttpBase() {
	if (process.env.REACT_APP_API_URL) return process.env.REACT_APP_API_URL;
	if (process.env.REACT_APP_WS_URL) {
		return process.env.REACT_APP_WS_URL.replace(/^ws/, "http").replace(
			/\/ws\/dashboard$/,
			"",
		);
	}
	const proto = window.location.protocol === "https:" ? "https" : "http";
	return `${proto}://${window.location.hostname}:8000`;
}

async function fetchJson(url, options) {
	const res = await fetch(url, options);
	if (!res.ok) {
		throw new Error(`HTTP ${res.status}`);
	}
	return res.json();
}

export function useRoverWebSocket() {
	const wsBaseRef = useRef(buildWsBase());
	const httpBaseRef = useRef(buildHttpBase());

	const [connected, setConnected] = useState(false);
	const [telemetry, setTelemetry] = useState(null);
	const [pathData, setPathData] = useState(null);
	const [alerts, setAlerts] = useState([]);
	const [status, setStatus] = useState({
		pi_connected: false,
		mission_active: false,
		rover_state: "STP",
		auto_mode: false,
		obstacle_active: false,
		victim_count: 0,
		motion_active: false,
		motion_mode: null,
		capabilities: { commands: DEFAULT_COMMANDS },
	});

	useEffect(() => {
		let ws = null;
		let cancelled = false;

		const connect = () => {
			if (cancelled) return;
			ws = new WebSocket(`${wsBaseRef.current}/ws/dashboard`);

			ws.onopen = () => {
				if (cancelled) return;
				setConnected(true);
			};

			ws.onmessage = (event) => {
				if (cancelled) return;
				try {
					const msg = JSON.parse(event.data);
					if (msg.type === 'init') {
						setTelemetry(msg.telemetry);
						setPathData(msg.path);
						setAlerts(msg.alerts || []);
						setStatus((prev) => ({
							...prev,
							...msg.status,
							capabilities: msg.status.capabilities || prev.capabilities,
						}));
					} else if (msg.type === 'telemetry') {
						setTelemetry(msg.telemetry);
						setPathData(msg.path);
					} else if (msg.type === 'event') {
						if (msg.alert) {
							setAlerts((prev) => [msg.alert, ...prev].slice(0, 50));
						}
					} else if (msg.type === 'heartbeat') {
						setStatus((prev) => ({
							...prev,
							...msg.status,
							capabilities: msg.status.capabilities || prev.capabilities,
						}));
					} else if (msg.type === 'victim') {
						setStatus((prev) => ({ ...prev, victim_count: msg.count }));
						if (msg.alert) {
							setAlerts((prev) => [msg.alert, ...prev].slice(0, 50));
						}
					} else if (msg.type === 'mode') {
						setStatus((prev) => ({
							...prev,
							motion_active: msg.status.motion_active,
							motion_mode: msg.status.motion_mode,
						}));
					}
				} catch (e) {
					console.error('WS message parse error:', e);
				}
			};

			ws.onclose = () => {
				if (cancelled) return;
				setConnected(false);
				// Reconnect after delay
				setTimeout(connect, 1000);
			};

			ws.onerror = (error) => {
				console.error('WS error:', error);
			};
		};

		connect();

		return () => {
			cancelled = true;
			if (ws) ws.close();
		};
	}, []);

	const sendCommand = useCallback(
		(cmd) => {
			const clean = (cmd || "").toUpperCase();
			const allowed = status?.capabilities?.commands || DEFAULT_COMMANDS;
			if (!allowed.includes(clean)) return;

			fetch(`${httpBaseRef.current}/api/command`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ command: clean }),
			}).catch(() => {});
		},
		[status],
	);

	const sendMode = useCallback(
		(mode) => {
			if (!mode) return;
			const allowed = status?.capabilities?.modes || [];
			const action = mode === "stop" ? "stop" : "start";
			if (action === "start" && !allowed.includes(mode)) return;

			fetch(`${httpBaseRef.current}/api/mode`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body:
					action === "stop"
						? JSON.stringify({ action: "stop" })
						: JSON.stringify({ mode }),
			}).catch(() => {});
		},
		[status],
	);

	return {
		connected,
		telemetry,
		pathData,
		alerts,
		status,
		sendCommand,
		sendMode,
		httpBase: httpBaseRef.current,
	};
}
