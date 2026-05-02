import { useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_COMMANDS = ["F", "B", "L", "R", "S"];

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
		let cancelled = false;

		const pollStatus = async () => {
			try {
				const data = await fetchJson(`${httpBaseRef.current}/api/status`);
				if (cancelled) return;
				setConnected(true);
				setStatus((prev) => ({
					...prev,
					...data,
					capabilities: data.capabilities || prev.capabilities,
				}));
			} catch (e) {
				if (!cancelled) setConnected(false);
			}
		};

		const pollTelemetry = async () => {
			try {
				const data = await fetchJson(
					`${httpBaseRef.current}/api/telemetry/history?limit=1`,
				);
				if (cancelled) return;
				const latest = data.telemetry?.[data.telemetry.length - 1] || null;
				if (latest) setTelemetry(latest);
			} catch (e) {
				// ignore telemetry errors
			}
		};

		const pollPath = async () => {
			try {
				const data = await fetchJson(`${httpBaseRef.current}/api/path`);
				if (cancelled) return;
				setPathData(data || null);
			} catch (e) {
				// ignore path errors
			}
		};

		const pollAlerts = async () => {
			try {
				const data = await fetchJson(
					`${httpBaseRef.current}/api/alerts?limit=50`,
				);
				if (cancelled) return;
				setAlerts(data.alerts || []);
			} catch (e) {
				// ignore alert errors
			}
		};

		pollStatus();
		pollTelemetry();
		pollPath();
		pollAlerts();

		const statusTimer = setInterval(pollStatus, 1000);
		const telemetryTimer = setInterval(pollTelemetry, 500);
		const pathTimer = setInterval(pollPath, 1000);
		const alertTimer = setInterval(pollAlerts, 2000);

		return () => {
			cancelled = true;
			clearInterval(statusTimer);
			clearInterval(telemetryTimer);
			clearInterval(pathTimer);
			clearInterval(alertTimer);
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
