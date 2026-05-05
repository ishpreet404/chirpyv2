import { useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_COMMANDS = ["F", "B", "L", "R", "S"];
const TELEMETRY_ARCHIVE_KEY = "rover_telemetry_archive";

function readStoredTelemetryArchive() {
	if (typeof window === "undefined") return [];
	try {
		const raw = window.localStorage.getItem(TELEMETRY_ARCHIVE_KEY);
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

function saveTelemetryArchive(items) {
	if (typeof window === "undefined") return;
	try {
		window.localStorage.setItem(
			TELEMETRY_ARCHIVE_KEY,
			JSON.stringify(items.slice(-2000)),
		);
	} catch {
		// ignore storage failures
	}
}

function buildWsBase() {
	if (process.env.REACT_APP_WS_URL) return process.env.REACT_APP_WS_URL;
	if (process.env.REACT_APP_API_URL) {
		return process.env.REACT_APP_API_URL.replace(/^http/, "ws");
	}
	const proto = window.location.protocol === "https:" ? "wss" : "ws";
	return `${proto}://${window.location.hostname}:8000`;
}

export function buildHttpBase() {
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
	const [telemetryArchive, setTelemetryArchive] = useState(() =>
		readStoredTelemetryArchive(),
	);
	const [pathData, setPathData] = useState(null);
	const [alerts, setAlerts] = useState([]);
	const [status, setStatus] = useState({
		pi_connected: false,
		mission_active: false,
		rover_state: "STP",
		auto_mode: false,
		victim_count: 0,
		motion_active: false,
		motion_mode: null,
		capabilities: { commands: DEFAULT_COMMANDS },
	});

	useEffect(() => {
		let ws = null;
		let cancelled = false;
		let archiveTimer = null;
		let routeTimer = null;

		const fetchTelemetryArchive = async () => {
			try {
				const data = await fetchJson(
					`${httpBaseRef.current}/api/telemetry/history?limit=500`,
				);
				if (cancelled) return;
				const archive = Array.isArray(data.telemetry) ? data.telemetry : [];
				setTelemetryArchive((prev) => {
					const merged = [...archive, ...prev];
					const deduped = merged.filter((item, index, list) => {
						const key = `${item?.seq ?? ""}:${item?.ms ?? ""}:${item?.abs_x ?? ""}:${item?.abs_y ?? ""}`;
						return (
							index ===
							list.findIndex(
								(entry) =>
									`${entry?.seq ?? ""}:${entry?.ms ?? ""}:${entry?.abs_x ?? ""}:${entry?.abs_y ?? ""}` ===
									key,
							)
						);
					});
					const next = deduped.slice(-2000);
					saveTelemetryArchive(next);
					return next;
				});
			} catch {
				// keep existing archive if backend history is unavailable
			}
		};

		const fetchRouteState = async () => {
			try {
				const data = await fetchJson(`${httpBaseRef.current}/api/route`);
				if (cancelled) return;
				setPathData((prev) => ({
					...(prev || {}),
					route: data.route ||
						prev?.route || {
							waypoints: [],
							status: "idle",
							paused: false,
							active_index: 0,
							name: null,
						},
				}));
			} catch {
				// route planning is optional; keep dashboard usable if the API is unavailable
			}
		};

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
					if (msg.type === "init") {
						setTelemetry(msg.telemetry);
						setPathData(msg.path);
						setAlerts(msg.alerts || []);
						setStatus((prev) => ({
							...prev,
							...msg.status,
							capabilities: msg.status.capabilities || prev.capabilities,
						}));
					} else if (msg.type === "telemetry") {
						setTelemetry(msg.telemetry);
						setPathData(msg.path);
						setTelemetryArchive((prev) => {
							const next = [...prev, msg.telemetry].slice(-2000);
							saveTelemetryArchive(next);
							return next;
						});
					} else if (msg.type === "route") {
						setPathData((prev) => ({
							...(prev || {}),
							...(msg.path || {}),
							route: msg.route || prev?.route || null,
						}));
					} else if (msg.type === "event") {
						if (msg.alert) {
							setAlerts((prev) => [msg.alert, ...prev].slice(0, 50));
						}
					} else if (msg.type === "heartbeat") {
						setStatus((prev) => ({
							...prev,
							...msg.status,
							capabilities: msg.status.capabilities || prev.capabilities,
						}));
					} else if (msg.type === "victim") {
						setStatus((prev) => ({ ...prev, victim_count: msg.count }));
						if (msg.alert) {
							setAlerts((prev) => [msg.alert, ...prev].slice(0, 50));
						}
					} else if (msg.type === "mode") {
						setStatus((prev) => ({
							...prev,
							motion_active: msg.status.motion_active,
							motion_mode: msg.status.motion_mode,
						}));
					}
				} catch (e) {
					console.error("WS message parse error:", e);
				}
			};

			ws.onclose = () => {
				if (cancelled) return;
				setConnected(false);
				// Reconnect after delay
				setTimeout(connect, 1000);
			};

			ws.onerror = (error) => {
				console.error("WS error:", error);
			};
		};

		connect();
		fetchTelemetryArchive();
		fetchRouteState();
		archiveTimer = window.setInterval(fetchTelemetryArchive, 15000);
		routeTimer = window.setInterval(fetchRouteState, 15000);

		return () => {
			cancelled = true;
			if (archiveTimer) window.clearInterval(archiveTimer);
			if (routeTimer) window.clearInterval(routeTimer);
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
		telemetryArchive,
		pathData,
		alerts,
		status,
		sendCommand,
		sendMode,
		httpBase: httpBaseRef.current,
	};
}
