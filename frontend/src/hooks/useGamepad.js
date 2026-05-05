import { useEffect, useRef, useState } from "react";

// Simple gamepad -> discrete rover command mapper.
// Maps left stick vertical to F/B, left stick horizontal to L/R, neutral -> S.
// Avoids spamming by only sending when desired command changes.

export function useGamepad(
	sendCommand,
	{ pollIntervalMs = 100, axisThreshold = 0.45 } = {},
) {
	const [connected, setConnected] = useState(false);
	const gpIndexRef = useRef(null);
	const lastCmdRef = useRef(null);
	const rafRef = useRef(null);
	const lastPollRef = useRef(0);
	const sendCommandRef = useRef(sendCommand);

	// Keep sendCommandRef in sync with sendCommand prop without causing re-runs
	useEffect(() => {
		sendCommandRef.current = sendCommand;
	}, [sendCommand]);

	useEffect(() => {
		function connectHandler(e) {
			gpIndexRef.current = e.gamepad.index;
			setConnected(true);
		}

		function disconnectHandler(e) {
			if (gpIndexRef.current === e.gamepad.index) gpIndexRef.current = null;
			setConnected(false);
			lastCmdRef.current = null;
		}

		window.addEventListener("gamepadconnected", connectHandler);
		window.addEventListener("gamepaddisconnected", disconnectHandler);

		// If a gamepad is already present, mark connected
		const gps = navigator.getGamepads ? navigator.getGamepads() : [];
		for (const gp of gps) {
			if (gp) {
				gpIndexRef.current = gp.index;
				setConnected(true);
				break;
			}
		}

		function poll(now) {
			const last = lastPollRef.current || 0;
			if (now - last >= pollIntervalMs) {
				lastPollRef.current = now;
				const idx = gpIndexRef.current;
				const gps = navigator.getGamepads ? navigator.getGamepads() : [];
				const gp = idx != null ? gps[idx] : gps[0];
				if (gp) {
					// Common mapping: axes[0] = left X, axes[1] = left Y
					const ax0 = gp.axes[0] || 0;
					const ax1 = gp.axes[1] || 0;
					// In many controllers up is -1, down is +1; forward -> up -> negative
					let desired = "S";
					if (Math.abs(ax1) > Math.abs(ax0)) {
						if (ax1 < -axisThreshold) desired = "F";
						else if (ax1 > axisThreshold) desired = "B";
					} else {
						if (ax0 < -axisThreshold) desired = "L";
						else if (ax0 > axisThreshold) desired = "R";
					}

					const last = lastCmdRef.current;
					if (desired !== last) {
						lastCmdRef.current = desired;
						try {
							sendCommandRef.current(desired);
						} catch (err) {
							// ignore send errors
						}
					}
				}
			}
			rafRef.current = requestAnimationFrame(poll);
		}

		rafRef.current = requestAnimationFrame(poll);

		return () => {
			window.removeEventListener("gamepadconnected", connectHandler);
			window.removeEventListener("gamepaddisconnected", disconnectHandler);
			if (rafRef.current) cancelAnimationFrame(rafRef.current);
		};
	}, [pollIntervalMs, axisThreshold]);

	return { connected };
}

export default useGamepad;
