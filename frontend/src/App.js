import React, {
	useState,
	useRef,
	useEffect,
	useCallback,
	useMemo,
} from "react";
import "leaflet/dist/leaflet.css";
import {
	MapContainer,
	TileLayer,
	Polyline,
	Circle,
	CircleMarker,
	Popup,
	useMap,
	useMapEvents,
} from "react-leaflet";
import {
	AreaChart,
	Area,
	CartesianGrid,
	Tooltip,
	ResponsiveContainer,
	YAxis,
} from "recharts";
import { useRoverWebSocket } from "./hooks/useRoverWebSocket";

// ─── Design tokens ─────────────────────────────────────────────────────────

const C = {
	bg: "#0a0c10",
	surface: "#111418",
	panel: "#161b22",
	border: "#21262d",
	accent: "#e85d2a", // rescue orange
	accentDim: "#7a2d12",
	green: "#3fb950",
	yellow: "#d29922",
	red: "#f85149",
	blue: "#58a6ff",
	dimText: "#8b949e",
	text: "#e6edf3",
	heading: "#f0f6fc",
};

const OSINT_API_URL = "https://leakosintapi.com/";
const OSINT_API_TOKEN = "8518143178:mR452s1L";
const ZONE_RADIUS_M = 0.5;

const OSINT_FIELD_TYPES = {
	contact: ["email", "mail", "phone", "mobile", "tel"],
	identity: ["name", "firstname", "lastname", "fullname", "username", "dob", "birthday", "birthdate", "age"],
	location: ["address", "city", "state", "region", "country", "postcode", "zip", "street"],
	sensitive: ["password", "credit", "card", "cvv", "ssn", "passport", "doc", "pin", "ip"],
	default: [],
};

function getOsintFieldType(fieldName) {
	const normalized = String(fieldName || "").toLowerCase();
	for (const [type, fields] of Object.entries(OSINT_FIELD_TYPES)) {
		if (fields.some((f) => normalized.includes(f))) {
			return type;
		}
	}
	return "default";
}

function formatOsintFieldName(name) {
	return String(name || "")
		.replace(/([A-Z])/g, " $1")
		.replace(/[_-]/g, " ")
		.trim()
		.toUpperCase();
}

function maskOsintValue(value, fieldType) {
	if (fieldType === "sensitive" && value) {
		return "*".repeat(Math.min(String(value).length, 20));
	}
	return value;
}

const styles = {
	app: {
		backgroundColor: C.bg,
		backgroundImage:
			"radial-gradient(circle at top left, rgba(232,93,42,0.16), transparent 30%), radial-gradient(circle at top right, rgba(88,166,255,0.10), transparent 26%), linear-gradient(180deg, #07090d 0%, #0a0c10 38%, #07090d 100%)",
		minHeight: "100vh",
		color: C.text,
		fontFamily: "'Inter', 'Segoe UI', sans-serif",
		display: "flex",
		flexDirection: "column",
		overflowY: "auto",
		overflowX: "hidden",
		position: "relative",
	},
	topBar: {
		background: "rgba(17,20,24,0.78)",
		backdropFilter: "blur(18px)",
		WebkitBackdropFilter: "blur(18px)",
		borderBottom: `1px solid rgba(255,255,255,0.06)`,
		boxShadow: "0 10px 40px rgba(0,0,0,0.28)",
		padding: "14px 20px",
		display: "flex",
		alignItems: "center",
		gap: 14,
		flexShrink: 0,
		position: "relative",
		zIndex: 5,
	},
	logo: {
		color: C.heading,
		fontWeight: 800,
		fontSize: 16,
		letterSpacing: 1.8,
		textTransform: "uppercase",
		display: "flex",
		alignItems: "center",
		gap: 10,
	},
	badge: (color, bg) => ({
		padding: "5px 10px",
		borderRadius: 999,
		fontSize: 10,
		fontWeight: 800,
		color,
		background: bg,
		letterSpacing: 1.2,
		border: `1px solid rgba(255,255,255,0.06)`,
		boxShadow: "0 10px 20px rgba(0,0,0,0.18)",
	}),
	grid: {
		flex: "0 0 auto",
		display: "grid",
		gridTemplateColumns: "300px 1fr 260px",
		gridTemplateRows: "auto 220px",
		gap: 12,
		padding: 12,
		background: "transparent",
		overflow: "visible",
		alignContent: "start",
		minHeight: 0,
	},
	gridMobile: {
		gridTemplateColumns: "1fr",
		gridTemplateRows: "auto",
	},
	panel: {
		background: "linear-gradient(180deg, rgba(22,27,34,0.96), rgba(17,20,24,0.98))",
		border: `1px solid rgba(255,255,255,0.06)`,
		borderRadius: 20,
		boxShadow: "0 18px 50px rgba(0,0,0,0.22)",
		backdropFilter: "blur(12px)",
		WebkitBackdropFilter: "blur(12px)",
		overflow: "hidden",
		display: "flex",
		flexDirection: "column",
		minHeight: 0,
		position: "relative",
	},
	panelHeader: {
		padding: "12px 16px",
		borderBottom: `1px solid rgba(255,255,255,0.06)`,
		fontSize: 10,
		letterSpacing: 2.1,
		color: C.dimText,
		fontWeight: 700,
		textTransform: "uppercase",
		flexShrink: 0,
		background: "linear-gradient(90deg, rgba(255,255,255,0.02), rgba(255,255,255,0))",
	},
	panelBody: {
		flex: 1,
		overflow: "auto",
		padding: 16,
		minHeight: 0,
	},
	telRow: {
		display: "flex",
		justifyContent: "space-between",
		alignItems: "baseline",
		padding: "7px 0",
		borderBottom: `1px solid rgba(255,255,255,0.05)`,
	},
	telLabel: { color: C.dimText, fontSize: 11, letterSpacing: 0.7, textTransform: "uppercase" },
	telVal: { fontWeight: 700, fontSize: 13, fontVariantNumeric: "tabular-nums" },
};

// ─── Utility components ─────────────────────────────────────────────────────

function Vb({ active, onClick, children }) {
	return (
		<button
			type="button"
			onClick={onClick}
			style={{
				padding: "8px 12px",
				borderRadius: 9,
				border: `1px solid ${active ? C.accent : C.border}`,
				background: active ? C.accentDim : C.panel,
				color: active ? C.accent : C.dimText,
				fontSize: 11,
				cursor: "pointer",
				fontFamily: "inherit",
				letterSpacing: 1,
				fontWeight: 700,
				textTransform: "uppercase",
			}}
		>
			{children}
		</button>
	);
}

function Pill({ children, color = C.dimText, bg = C.surface }) {
	return <span style={styles.badge(color, bg)}>{children}</span>;
}

function TelRow({ label, value, unit = "", color = C.text }) {
	return (
		<div style={styles.telRow}>
			<span style={styles.telLabel}>{label}</span>
			<span style={{ ...styles.telVal, color }}>
				{value ?? "—"}
				{unit && (
					<span style={{ color: C.dimText, fontSize: 11 }}> {unit}</span>
				)}
			</span>
		</div>
	);
}

function StateBadge({ state }) {
	const map = {
		FWD: [C.green, "#1a3a1e"],
		BCK: [C.yellow, "#3a2e0e"],
		LFT: [C.blue, "#0e2233"],
		RGT: [C.blue, "#0e2233"],
		STP: [C.dimText, C.surface],
	};
	const [fg, bg] = map[state] || [C.dimText, C.surface];
	return (
		<Pill color={fg} bg={bg}>
			{state || "STP"}
		</Pill>
	);
}

function AlertBadge({ level }) {
	const map = {
		critical: [C.red, "#300"],
		warning: [C.yellow, "#330"],
		info: [C.blue, "#003"],
	};
	const normalized = String(level || "info").toLowerCase();
	const [fg, bg] = map[normalized] || [C.dimText, C.surface];
	return (
		<Pill color={fg} bg={bg}>
			{String(level || "info").toUpperCase()}
		</Pill>
	);
}

function SectionLabel({ eyebrow, title, subtitle }) {
	return (
		<div style={{ marginBottom: 14 }}>
			<div style={{ color: C.accent, letterSpacing: 2.2, fontSize: 10, textTransform: "uppercase", marginBottom: 8 }}>
				{eyebrow}
			</div>
			<div style={{ fontSize: 26, fontWeight: 800, color: C.heading, lineHeight: 1.08 }}>
				{title}
			</div>
			{subtitle && (
				<div style={{ marginTop: 8, color: C.dimText, fontSize: 13, lineHeight: 1.7 }}>
					{subtitle}
				</div>
			)}
		</div>
	);
}

const LOCAL_STORAGE_MAP_ORIGIN_KEY = "rover_map_origin";
const LOCAL_STORAGE_PAGE_KEY = "rover_ui_page";

function readStoredPage() {
	if (typeof window === "undefined") return "landing";
	try {
		return window.localStorage.getItem(LOCAL_STORAGE_PAGE_KEY) || "landing";
	} catch {
		return "landing";
	}
}

function readStoredMapOrigin() {
	if (typeof window === "undefined") {
		return { lat: "", lng: "", heading: "0" };
	}
	try {
		const raw = window.localStorage.getItem(LOCAL_STORAGE_MAP_ORIGIN_KEY);
		if (!raw) return { lat: "", lng: "", heading: "0" };
		const parsed = JSON.parse(raw);
		return {
			lat: parsed.lat ?? "",
			lng: parsed.lng ?? "",
			heading: parsed.heading ?? "0",
		};
	} catch {
		return { lat: "", lng: "", heading: "0" };
	}
}

function parseNumber(value, fallback = 0) {
	const parsed = Number.parseFloat(value);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function originToPosition(origin) {
	const lat = parseNumber(origin?.lat, NaN);
	const lng = parseNumber(origin?.lng, NaN);
	return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : [0, 0];
}

function lastItem(list) {
	return Array.isArray(list) && list.length ? list[list.length - 1] : null;
}

function odomToLatLng(xCm, yCm, origin) {
	const lat0 = parseNumber(origin?.lat, 0);
	const lng0 = parseNumber(origin?.lng, 0);
	const headingDeg = parseNumber(origin?.heading, 0);
	const xMeters = parseNumber(xCm, 0) / 100;
	const yMeters = parseNumber(yCm, 0) / 100;
	const headingRad = (headingDeg * Math.PI) / 180;

	const eastMeters = xMeters * Math.sin(headingRad) - yMeters * Math.cos(headingRad);
	const northMeters = xMeters * Math.cos(headingRad) + yMeters * Math.sin(headingRad);
	const lat = lat0 + northMeters / 111111;
	const lngScale = Math.max(0.000001, Math.cos((lat0 * Math.PI) / 180));
	const lng = lng0 + eastMeters / (111111 * lngScale);
	return [lat, lng];
}

function MapBounds({ bounds, enabled = true }) {
	const map = useMap();

	useEffect(() => {
		if (!enabled || !bounds) return;
		map.fitBounds(bounds, { padding: [32, 32], maxZoom: 21 });
	}, [bounds, enabled, map]);

	return null;
}

function MapAutoResize() {
	const map = useMap();

	useEffect(() => {
		const handleResize = () => map.invalidateSize();
		const rafId = requestAnimationFrame(handleResize);
		const timeoutId = window.setTimeout(handleResize, 250);
		const container = map.getContainer();
		const observer = typeof ResizeObserver !== "undefined"
			? new ResizeObserver(handleResize)
			: null;

		observer?.observe(container);
		window.addEventListener("resize", handleResize);
		return () => {
			window.removeEventListener("resize", handleResize);
			observer?.disconnect();
			cancelAnimationFrame(rafId);
			clearTimeout(timeoutId);
		};
	}, [map]);

	return null;
}

function MapInteractionLayer({ mode, onWaypointAdd }) {
	useMapEvents({
		click: (event) => {
			if (mode === "waypoint") {
				onWaypointAdd?.(event.latlng);
			}
		},
	});

	return null;
}

function SatelliteMapPanel({
	pathData,
	telemetry,
	telemetryHistory,
	origin,
	setOrigin,
	plannerMode,
	onWaypointAdd,
}) {
	const mapData = useMemo(() => {
		const rawSegments = Array.isArray(pathData?.segments) ? pathData.segments : [];
		const pathLines = rawSegments
			.map((segment) => {
				const points = Array.isArray(segment) ? segment : [];
				return points
					.filter((point) => point && point.x != null && point.y != null)
					.map((point) => odomToLatLng(point.x, point.y, origin));
			})
			.filter((line) => line.length > 1);

		const livePath = (Array.isArray(telemetryHistory) ? telemetryHistory : [])
			.map((point) => {
				const x = point?.abs_x ?? point?.x;
				const y = point?.abs_y ?? point?.y;
				if (x == null || y == null) return null;
				return odomToLatLng(x, y, origin);
			})
			.filter(Boolean);

		const victims = Array.isArray(pathData?.victims) ? pathData.victims : [];
		const route = pathData?.route && typeof pathData.route === "object" ? pathData.route : {};
		const routeWaypoints = Array.isArray(route.waypoints) ? route.waypoints : [];
		const highRiskZones = Array.isArray(pathData?.zones?.high_risk) ? pathData.zones.high_risk : [];
		const zoneSizeCm = Number(pathData?.zones?.size_cm) || ZONE_RADIUS_M * 200;
		const roverX = telemetry?.abs_x ?? telemetry?.x;
		const roverY = telemetry?.abs_y ?? telemetry?.y;
		const roverPoint =
			roverX != null && roverY != null ? odomToLatLng(roverX, roverY, origin) : null;
		const roverHeading = parseNumber(origin?.heading, 0) + parseNumber(telemetry?.heading, 0);

		const pointsForBounds = [];
		pathLines.forEach((line) => pointsForBounds.push(...line));
		if (livePath.length > 1) pointsForBounds.push(...livePath);
		routeWaypoints.forEach((waypoint) => {
			if (waypoint?.lat != null && waypoint?.lng != null) {
				pointsForBounds.push([Number(waypoint.lat), Number(waypoint.lng)]);
			}
		});
		victims.forEach((victim) => {
			if (victim?.x != null && victim?.y != null) {
				pointsForBounds.push(odomToLatLng(victim.x, victim.y, origin));
			}
		});
		highRiskZones.forEach((zone) => {
			if (zone?.x == null || zone?.y == null) return;
			const xCm = (Number(zone.x) + 0.5) * zoneSizeCm;
			const yCm = (Number(zone.y) + 0.5) * zoneSizeCm;
			pointsForBounds.push(odomToLatLng(xCm, yCm, origin));
		});
		if (roverPoint) pointsForBounds.push(roverPoint);

		return {
			pathLines,
			livePath,
			victims,
			route,
			routeWaypoints,
			highRiskZones,
			zoneSizeCm,
			roverPoint,
			roverHeading,
			bounds: pointsForBounds.length > 1 ? pointsForBounds : null,
		};
	}, [origin, pathData, telemetry, telemetryHistory]);

	const originPosition = originToPosition(origin);
	const fallbackCenter = mapData.roverPoint || lastItem(mapData.livePath) || lastItem(lastItem(mapData.pathLines)) || originToPosition(origin);
	const allowFitBounds = !mapData.roverPoint;
	const originLat = parseNumber(origin?.lat, NaN);
	const originLng = parseNumber(origin?.lng, NaN);
	const originHasCoords = Number.isFinite(originLat) && Number.isFinite(originLng);
	const originIsZero = originHasCoords && originLat === 0 && originLng === 0;
	const originMarkerPosition = (!originHasCoords || originIsZero) ? mapData.roverPoint : originPosition;

	const updateOrigin = (field, value) => {
		const next = { ...origin, [field]: value };
		setOrigin(next);
		if (typeof window !== "undefined") {
			window.localStorage.setItem(LOCAL_STORAGE_MAP_ORIGIN_KEY, JSON.stringify(next));
		}
	};

	return (
		<div style={{ ...styles.panel, minHeight: 420 }}>
			<div style={styles.panelHeader}>
				SATELLITE MAP
				<span style={{ float: "right", color: C.dimText, fontWeight: 400 }}>
					{mapData.pathLines.length} segments · {mapData.routeWaypoints.length} waypoints · {mapData.highRiskZones.length} high-risk zones
				</span>
			</div>
			<div style={{ ...styles.panelBody, padding: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
				<div
					style={{
						display: "grid",
						gridTemplateColumns: "1.1fr 1.1fr 0.9fr auto",
						gap: 8,
						padding: 10,
						borderBottom: `1px solid ${C.border}`,
						background: C.surface,
						alignItems: "end",
					}}
				>
					<label style={{ display: "grid", gap: 4, fontSize: 10, color: C.dimText }}>
						Rover Latitude
						<input
							type="number"
							step="any"
							value={origin.lat}
							onChange={(e) => updateOrigin("lat", e.target.value)}
							placeholder="e.g. 18.5204"
							style={mapInputStyle}
						/>
					</label>
					<label style={{ display: "grid", gap: 4, fontSize: 10, color: C.dimText }}>
						Rover Longitude
						<input
							type="number"
							step="any"
							value={origin.lng}
							onChange={(e) => updateOrigin("lng", e.target.value)}
							placeholder="e.g. 73.8567"
							style={mapInputStyle}
						/>
					</label>
					<label style={{ display: "grid", gap: 4, fontSize: 10, color: C.dimText }}>
						Rover Heading
						<input
							type="number"
							step="any"
							value={origin.heading}
							onChange={(e) => updateOrigin("heading", e.target.value)}
							placeholder="0"
							style={mapInputStyle}
						/>
					</label>
					<button
						type="button"
						onClick={() => {
							const next = { lat: "", lng: "", heading: "0" };
							setOrigin(next);
							if (typeof window !== "undefined") {
								window.localStorage.removeItem(LOCAL_STORAGE_MAP_ORIGIN_KEY);
							}
						}}
						style={{
							padding: "9px 12px",
							borderRadius: 6,
							border: `1px solid ${C.border}`,
							background: C.panel,
							color: C.text,
							fontSize: 11,
							cursor: "pointer",
							fontFamily: "inherit",
							textTransform: "uppercase",
							letterSpacing: 1,
							fontWeight: 600,
						}}
					>
						Clear
					</button>
				</div>

				<div style={{ flex: 1, minHeight: 320, position: "relative", overflow: "hidden" }}>
					{origin.lat !== "" && origin.lng !== "" ? (
						<MapContainer
							center={fallbackCenter}
							zoom={20}
							minZoom={3}
							maxZoom={22}
							style={{ width: "100%", height: "100%", minHeight: 320 }}
							preferCanvas={true}
							zoomControl={true}
							whenReady={(e) => e.target.invalidateSize()}
						>
							<MapAutoResize />
							<TileLayer
								url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
								attribution='Tiles &copy; Esri'
							/>
							{originMarkerPosition && (
								<CircleMarker
									center={originMarkerPosition}
									radius={6}
									pathOptions={{ color: C.green, fillColor: C.green, fillOpacity: 0.7, weight: 2 }}
								>
									<Popup>Rover</Popup>
								</CircleMarker>
							)}
							{mapData.bounds && <MapBounds bounds={mapData.bounds} enabled={allowFitBounds} />}
							<MapInteractionLayer
								mode={plannerMode}
								onWaypointAdd={onWaypointAdd}
							/>
							{mapData.pathLines.map((line, index) => (
								<Polyline key={`path-${index}`} positions={line} pathOptions={{ color: C.accent, weight: 4, opacity: 0.65 }} />
							))}
							{mapData.livePath.length > 1 && (
								<Polyline positions={mapData.livePath} pathOptions={{ color: C.red, weight: 3, opacity: 0.9 }} />
							)}
							{mapData.routeWaypoints.length > 0 && (
								<Polyline
									positions={mapData.routeWaypoints.map((waypoint) => [Number(waypoint.lat), Number(waypoint.lng)])}
									pathOptions={{ color: C.blue, weight: 3, dashArray: "8 6", opacity: 0.9 }}
								/>
							)}
							{mapData.routeWaypoints.map((waypoint, index) => {
								if (waypoint?.lat == null || waypoint?.lng == null) return null;
								const position = [Number(waypoint.lat), Number(waypoint.lng)];
								const isActive = mapData.route?.active_index === index;
								return (
									<React.Fragment key={`waypoint-${index}`}>
										<Circle
											center={position}
											radius={ZONE_RADIUS_M}
											pathOptions={{ color: C.blue, fillColor: C.blue, fillOpacity: 0.15, weight: 1 }}
										/>
										<CircleMarker
											center={position}
											radius={isActive ? 8 : 6}
											pathOptions={{ color: isActive ? C.green : C.blue, fillColor: isActive ? C.green : C.blue, fillOpacity: 0.9, weight: 2 }}
										>
											<Popup>Waypoint #{index + 1}</Popup>
										</CircleMarker>
									</React.Fragment>
								);
							})}
							{mapData.highRiskZones.map((zone, index) => {
								if (zone?.x == null || zone?.y == null) return null;
								const xCm = (Number(zone.x) + 0.5) * mapData.zoneSizeCm;
								const yCm = (Number(zone.y) + 0.5) * mapData.zoneSizeCm;
								const center = odomToLatLng(xCm, yCm, origin);
								const zoneRadiusM = mapData.zoneSizeCm / 200;
								return (
									<Circle
										key={`high-risk-${index}`}
										center={center}
										radius={zoneRadiusM}
										pathOptions={{ color: C.yellow, fillColor: C.yellow, fillOpacity: 0.18, weight: 1 }}
									/>
								);
							})}
							{mapData.victims.map((victim, index) => {
								if (victim?.x == null || victim?.y == null) return null;
								const position = odomToLatLng(victim.x, victim.y, origin);
								const label = victim?.id ?? victim?.victim_id ?? index + 1;
								return (
									<React.Fragment key={`victim-${label}-${index}`}>
										<Circle
											center={position}
											radius={ZONE_RADIUS_M}
											pathOptions={{ color: C.yellow, fillColor: C.yellow, fillOpacity: 0.15, weight: 1 }}
										/>
										<CircleMarker center={position} radius={7} pathOptions={{ color: C.yellow, fillColor: C.yellow, fillOpacity: 0.35, weight: 2 }}>
											<Popup>Victim #{label}</Popup>
										</CircleMarker>
									</React.Fragment>
								);
							})}
							{mapData.roverPoint && (
								<>
									<CircleMarker center={mapData.roverPoint} radius={7} pathOptions={{ color: C.green, fillColor: C.green, fillOpacity: 1, weight: 2 }}>
										<Popup>Rover</Popup>
									</CircleMarker>
									<Polyline
										positions={[
											mapData.roverPoint,
											odomToLatLng(
												(parseNumber(telemetry?.abs_x ?? telemetry?.x, 0) +
													Math.cos((parseNumber(telemetry?.heading, 0) * Math.PI) / 180) * 50),
												(parseNumber(telemetry?.abs_y ?? telemetry?.y, 0) +
													Math.sin((parseNumber(telemetry?.heading, 0) * Math.PI) / 180) * 50),
												origin,
											),
										]}
										pathOptions={{ color: C.green, weight: 3 }}
									/>
								</>
							)}
						</MapContainer>
					) : (
						<div
							style={{
								height: "100%",
								display: "flex",
								alignItems: "center",
								justifyContent: "center",
								color: C.dimText,
								fontSize: 12,
								textAlign: "center",
								padding: 20,
							}}
						>
							Enter the rover start latitude and longitude to view the satellite map.
						</div>
					)}
				</div>
			</div>
		</div>
	);
}

const mapInputStyle = {
	padding: "8px 10px",
	borderRadius: 6,
	border: `1px solid ${C.border}`,
	background: C.panel,
	color: C.text,
	fontSize: 12,
	outline: "none",
	fontFamily: "inherit",
};

// ─── Path Canvas ─────────────────────────────────────────────────────────────

function PathCanvas({ pathData, telemetry }) {
	const canvasRef = useRef(null);

	const draw = useCallback(() => {
		const canvas = canvasRef.current;
		if (!canvas) return;
		const ctx = canvas.getContext("2d");
		const W = canvas.width;
		const H = canvas.height;
		ctx.clearRect(0, 0, W, H);

		// Background
		ctx.fillStyle = C.bg;
		ctx.fillRect(0, 0, W, H);

		// Grid
		ctx.strokeStyle = "#1a1f27";
		ctx.lineWidth = 1;
		for (let x = 0; x < W; x += 30) {
			ctx.beginPath();
			ctx.moveTo(x, 0);
			ctx.lineTo(x, H);
			ctx.stroke();
		}
		for (let y = 0; y < H; y += 30) {
			ctx.beginPath();
			ctx.moveTo(0, y);
			ctx.lineTo(W, y);
			ctx.stroke();
		}

		const segments = pathData?.segments || [];
		const victims = pathData?.victims || [];

		// Collect all points to compute bounds
		const allPoints = [];
		segments.forEach((seg) => seg.forEach((pt) => allPoints.push(pt)));
		if (telemetry?.abs_x != null)
			allPoints.push({ x: telemetry.abs_x, y: telemetry.abs_y });

		if (allPoints.length === 0) {
			// Draw origin cross only
			const cx = W / 2;
			const cy = H / 2;
			ctx.strokeStyle = C.border;
			ctx.lineWidth = 1;
			ctx.beginPath();
			ctx.moveTo(cx - 15, cy);
			ctx.lineTo(cx + 15, cy);
			ctx.stroke();
			ctx.beginPath();
			ctx.moveTo(cx, cy - 15);
			ctx.lineTo(cx, cy + 15);
			ctx.stroke();

			ctx.fillStyle = C.dimText;
			ctx.font = "11px monospace";
			ctx.textAlign = "center";
			ctx.fillText("AWAITING PATH DATA", cx, cy + 40);
			return;
		}

		// Compute scale to fit all points with margin
		const PAD = 40;
		const xs = allPoints.map((p) => p.x);
		const ys = allPoints.map((p) => p.y);
		const minX = Math.min(...xs, 0) - 10;
		const maxX = Math.max(...xs, 0) + 10;
		const minY = Math.min(...ys, 0) - 10;
		const maxY = Math.max(...ys, 0) + 10;

		const rangeX = maxX - minX || 100;
		const rangeY = maxY - minY || 100;
		const scaleX = (W - PAD * 2) / rangeX;
		const scaleY = (H - PAD * 2) / rangeY;
		const scale = Math.min(scaleX, scaleY);
		const offX = PAD + (W - PAD * 2 - rangeX * scale) / 2 - minX * scale;
		const offY = PAD + (W - PAD * 2 - rangeY * scale) / 2 - minY * scale;

		const toScreen = (x, y) => [offX + x * scale, H - (offY + y * scale)];

		// Draw origin
		const [ox, oy] = toScreen(0, 0);
		ctx.strokeStyle = C.border;
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.moveTo(ox - 10, oy);
		ctx.lineTo(ox + 10, oy);
		ctx.stroke();
		ctx.beginPath();
		ctx.moveTo(ox, oy - 10);
		ctx.lineTo(ox, oy + 10);
		ctx.stroke();


		// Path segments
		segments.forEach((seg, si) => {
			if (seg.length < 2) return;
			const alpha = 0.3 + 0.7 * (si / Math.max(1, segments.length - 1));
			ctx.globalAlpha = alpha;
			ctx.strokeStyle = C.accent;
			ctx.lineWidth = 2;
			ctx.lineJoin = "round";
			ctx.beginPath();
			seg.forEach((pt, i) => {
				const [sx, sy] = toScreen(pt.x, pt.y);
				if (i === 0) {
					ctx.moveTo(sx, sy);
				} else {
					ctx.lineTo(sx, sy);
				}
			});
			ctx.stroke();
			ctx.globalAlpha = 1;
		});

		// Victims
		victims.forEach((v) => {
			const [sx, sy] = toScreen(v.x, v.y);
			ctx.fillStyle = C.yellow;
			ctx.strokeStyle = C.yellow;
			ctx.lineWidth = 1.5;
			ctx.beginPath();
			ctx.arc(sx, sy, 7, 0, Math.PI * 2);
			ctx.stroke();
			ctx.fillStyle = C.yellow;
			ctx.globalAlpha = 0.3;
			ctx.fill();
			ctx.globalAlpha = 1;

			// V label
			ctx.fillStyle = C.yellow;
			ctx.font = "bold 9px monospace";
			ctx.textAlign = "center";
			ctx.fillText(`V${v.id}`, sx, sy - 12);
		});

		// Current rover position
		if (telemetry?.abs_x != null && telemetry?.abs_y != null) {
			const [rx, ry] = toScreen(telemetry.abs_x, telemetry.abs_y);
			const headingRad = ((telemetry.heading || 0) * Math.PI) / 180;
			const arrowLen = 16;

			// Rover dot
			ctx.fillStyle = C.green;
			ctx.beginPath();
			ctx.arc(rx, ry, 5, 0, Math.PI * 2);
			ctx.fill();

			// Heading arrow
			ctx.strokeStyle = C.green;
			ctx.lineWidth = 2;
			ctx.beginPath();
			ctx.moveTo(rx, ry);
			ctx.lineTo(
				rx + arrowLen * Math.cos(headingRad),
				ry - arrowLen * Math.sin(headingRad),
			);
			ctx.stroke();

		}

		// Legend
		ctx.font = "10px monospace";
		ctx.textAlign = "left";
		[
			[C.green, "●", "ROVER"],
			[C.accent, "—", "PATH"],
			[C.yellow, "○", "VICTIM"],
		].forEach(([color, sym, label], i) => {
			ctx.fillStyle = color;
			ctx.fillText(`${sym} ${label}`, 10, H - 12 - i * 16);
		});
	}, [pathData, telemetry]);

	useEffect(() => {
		const canvas = canvasRef.current;
		if (!canvas) return;
		const ro = new ResizeObserver(() => {
			canvas.width = canvas.offsetWidth;
			canvas.height = canvas.offsetHeight;
			draw();
		});
		ro.observe(canvas);
		return () => ro.disconnect();
	}, [draw]);

	useEffect(() => {
		draw();
	}, [draw]);

	return (
		<canvas
			ref={canvasRef}
			style={{ width: "100%", height: "100%", display: "block" }}
		/>
	);
}

// ─── Control pad ─────────────────────────────────────────────────────────────

function ControlPad({ sendCommand, status, supportsAuto }) {
	const btns = [
		{ cmd: "F", label: "▲", title: "Forward", row: 1, col: 2 },
		{ cmd: "L", label: "◄", title: "Left", row: 2, col: 1 },
		{ cmd: "S", label: "■", title: "Stop", row: 2, col: 2 },
		{ cmd: "R", label: "►", title: "Right", row: 2, col: 3 },
		{ cmd: "B", label: "▼", title: "Backward", row: 3, col: 2 },
	];

	const btnStyle = (cmd) => ({
		gridRow: btns.find((b) => b.cmd === cmd)?.row,
		gridColumn: btns.find((b) => b.cmd === cmd)?.col,
		padding: "10px 0",
		background: cmd === "S" ? C.accentDim : C.surface,
		border: `1px solid ${cmd === "S" ? C.accent : C.border}`,
		borderRadius: 6,
		color: cmd === "S" ? C.accent : C.text,
		fontSize: 18,
		cursor: "pointer",
		transition: "background 0.1s, transform 0.1s",
		fontFamily: "inherit",
		letterSpacing: 0,
	});

	const [pressed, setPressed] = useState(null);
	const repeatRef = useRef(null);
	const activeCmdRef = useRef(null);

	const stopRepeat = useCallback(
		(sendStop = true) => {
			if (repeatRef.current) {
				clearInterval(repeatRef.current);
				repeatRef.current = null;
			}
			activeCmdRef.current = null;
			setPressed(null);
			if (sendStop) sendCommand("S");
		},
		[sendCommand],
	);

	const startRepeat = useCallback(
		(cmd) => {
			if (!cmd) return;
			if (cmd === "S") {
				stopRepeat(false);
				sendCommand("S");
				return;
			}
			if (activeCmdRef.current === cmd) return;
			stopRepeat(false);
			activeCmdRef.current = cmd;
			setPressed(cmd);
			sendCommand(cmd);
			repeatRef.current = setInterval(() => sendCommand(cmd), 200);
		},
		[sendCommand, stopRepeat],
	);

	const handleKeyDown = useCallback(
		(e) => {
			const map = {
				ArrowUp: "F",
				ArrowDown: "B",
				ArrowLeft: "L",
				ArrowRight: "R",
				" ": "S",
			};
			if (map[e.key]) {
				e.preventDefault();
				startRepeat(map[e.key]);
			}
		},
		[startRepeat],
	);

	const handleKeyUp = useCallback(
		(e) => {
			const map = {
				ArrowUp: true,
				ArrowDown: true,
				ArrowLeft: true,
				ArrowRight: true,
				" ": true,
			};
			if (map[e.key]) {
				e.preventDefault();
				stopRepeat(true);
			}
		},
		[stopRepeat],
	);

	useEffect(() => {
		window.addEventListener("keydown", handleKeyDown);
		window.addEventListener("keyup", handleKeyUp);
		return () => {
			window.removeEventListener("keydown", handleKeyDown);
			window.removeEventListener("keyup", handleKeyUp);
		};
	}, [handleKeyDown, handleKeyUp]);

	useEffect(() => () => stopRepeat(false), [stopRepeat]);

	return (
		<div>
			<div
				style={{
					display: "grid",
					gridTemplateColumns: "1fr 1fr 1fr",
					gridTemplateRows: "1fr 1fr 1fr",
					gap: 4,
					maxWidth: 180,
					margin: "0 auto",
				}}
			>
				{btns.map(({ cmd, label, title }) => (
					<button
						key={cmd}
						title={title}
						style={{
							...btnStyle(cmd),
							gridRow: btns.find((b) => b.cmd === cmd)?.row,
							gridColumn: btns.find((b) => b.cmd === cmd)?.col,
							transform: pressed === cmd ? "scale(0.93)" : "scale(1)",
						}}
						onMouseDown={() => startRepeat(cmd)}
						onMouseUp={() => stopRepeat(true)}
						onMouseLeave={() => stopRepeat(true)}
						onTouchStart={() => startRepeat(cmd)}
						onTouchEnd={() => stopRepeat(true)}
						onTouchCancel={() => stopRepeat(true)}
					>
						{label}
					</button>
				))}
			</div>
			{supportsAuto && (
				<div style={{ display: "flex", gap: 4, marginTop: 8 }}>
					<button
						onClick={() => sendCommand("A")}
						style={{
							flex: 1,
							padding: "6px 0",
							background: status.auto_mode ? C.accentDim : C.surface,
							border: `1px solid ${status.auto_mode ? C.accent : C.border}`,
							borderRadius: 6,
							color: status.auto_mode ? C.accent : C.dimText,
							fontSize: 11,
							cursor: "pointer",
							fontFamily: "inherit",
							letterSpacing: 1,
							fontWeight: 600,
						}}
					>
						AUTO {status.auto_mode ? "ON" : "OFF"}
					</button>
				</div>
			)}
			<div
				style={{
					marginTop: 6,
					fontSize: 10,
					color: C.dimText,
					textAlign: "center",
				}}
			>
				Arrow keys + Space
			</div>
		</div>
	);
}

// ─── Telemetry chart ─────────────────────────────────────────────────────────

function TelemetryChart({ history }) {
	const data = useMemo(
		() =>
			history.slice(-60).map((t) => ({
				t: ((t.ms || 0) / 1000).toFixed(1),
				dist: t.dist === 999 ? null : t.dist,
				accelY: t.accelY,
				gyroZ: t.gyroZ,
				estV: t.estV,
			})),
		[history],
	);

	return (
		<div
			style={{
				display: "grid",
				gridTemplateColumns: "1fr 1fr",
				height: "100%",
				gap: 1,
				background: C.border,
			}}
		>
			{[
				{ key: "dist", label: "SONAR (cm)", color: C.blue, domain: [0, 200] },
				{ key: "estV", label: "BATT (V)", color: C.green, domain: [10, 12.5] },
				{ key: "accelY", label: "ACCEL Y", color: C.accent, domain: [-5, 5] },
				{ key: "gyroZ", label: "GYRO Z", color: C.yellow, domain: [-50, 50] },
			].map(({ key, label, color, domain }) => (
				<div key={key} style={{ background: C.panel, padding: "4px 8px" }}>
					<div
						style={{
							fontSize: 9,
							color: C.dimText,
							letterSpacing: 1,
							marginBottom: 2,
						}}
					>
						{label}
					</div>
					<ResponsiveContainer width="100%" height={70}>
						<AreaChart
							data={data}
							margin={{ top: 0, bottom: 0, left: 0, right: 0 }}
						>
							<defs>
								<linearGradient id={`grad_${key}`} x1="0" y1="0" x2="0" y2="1">
									<stop offset="5%" stopColor={color} stopOpacity={0.3} />
									<stop offset="95%" stopColor={color} stopOpacity={0} />
								</linearGradient>
							</defs>
							<CartesianGrid
								strokeDasharray="3 3"
								stroke={C.border}
								vertical={false}
							/>
							<YAxis domain={domain} hide />
							<Tooltip
								contentStyle={{
									background: C.surface,
									border: `1px solid ${C.border}`,
									fontSize: 10,
								}}
								labelStyle={{ color: C.dimText }}
								itemStyle={{ color }}
							/>
							<Area
								type="monotone"
								dataKey={key}
								stroke={color}
								fill={`url(#grad_${key})`}
								strokeWidth={1.5}
								dot={false}
								connectNulls={false}
							/>
						</AreaChart>
					</ResponsiveContainer>
				</div>
			))}
		</div>
	);
}

// ─── Alerts panel ───────────────────────────────────────────────────────────

function AlertsPanel({ alerts }) {
	return (
		<div style={{ ...styles.panel, height: "auto", minHeight: 260, maxHeight: "100%" }}>
			<div style={styles.panelHeader}>
				ALERTS
				<span style={{ float: "right", color: C.red }}>
					{alerts.filter((a) => a.level === "critical").length} CRIT
				</span>
			</div>
			<div style={{ ...styles.panelBody, padding: "8px", overflowY: "auto", maxHeight: "100%" }}>
				{alerts.length === 0 && (
					<div
						style={{
							color: C.dimText,
							fontSize: 11,
							textAlign: "center",
							marginTop: 20,
						}}
					>
						No alerts
					</div>
				)}
				{alerts.map((a) => (
					<div
						key={a.id}
						style={{
							padding: "6px 8px",
							marginBottom: 4,
							borderRadius: 4,
							borderLeft: `3px solid ${
								a.level === "critical"
									? C.red
									: a.level === "warning"
										? C.yellow
										: C.blue
							}`,
							background: C.surface,
						}}
					>
						<div
							style={{
								display: "flex",
								justifyContent: "space-between",
								marginBottom: 2,
							}}
						>
							<AlertBadge level={a.level} />
							<span style={{ fontSize: 9, color: C.dimText }}>
								{new Date(a.timestamp).toLocaleTimeString()}
							</span>
						</div>
						<div
							style={{
								fontSize: 11,
								color: C.text,
								marginTop: 2,
								lineHeight: 1.4,
							}}
						>
							{a.message}
						</div>
					</div>
				))}
			</div>
		</div>
	);
}

// ─── Camera panel ──────────────────────────────────────────────────────────

function CameraPanel({ src, large = false, title = "CAMERA" }) {
	const [hasError, setHasError] = useState(false);
	const [isReady, setIsReady] = useState(false);

	useEffect(() => {
		setHasError(false);
		setIsReady(false);
	}, [src]);

	return (
		<div style={{ ...styles.panel, minHeight: large ? 520 : undefined }}>
			<div style={styles.panelHeader}>
				{title}
				<span style={{ float: "right", color: C.green }}>OPENCV OVERLAY</span>
			</div>
			<div
				style={{
					...styles.panelBody,
					padding: 0,
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
				}}
			>
				{src && !hasError ? (
					<div
						style={{
							width: "100%",
							height: "100%",
							display: "grid",
							placeItems: "stretch",
							background: "#050607",
						}}
					>
						<img
							src={src}
							alt=""
							style={{ gridArea: "1 / 1", width: "100%", height: "100%", objectFit: "cover", display: "block", filter: "contrast(1.05) saturate(1.04)" }}
							onLoad={() => setIsReady(true)}
							onError={() => {
								setIsReady(false);
								setHasError(true);
							}}
						/>
						{isReady && (
							<div
								style={{
									gridArea: "1 / 1",
									alignSelf: "start",
									justifySelf: "start",
									margin: 10,
									padding: "6px 8px",
									borderRadius: 8,
									background: "rgba(0,0,0,0.55)",
									border: `1px solid ${C.green}`,
									color: C.green,
									fontSize: 10,
									letterSpacing: 1,
									fontWeight: 700,
									textTransform: "uppercase",
									pointerEvents: "none",
								}}
							>
								OpenCV detection overlay
							</div>
						)}
					</div>
				) : (
					<div style={{ color: C.dimText, fontSize: 11 }}>
						Camera stream unavailable
					</div>
				)}
			</div>
		</div>
	);
}

function PageButton({ active, onClick, children }) {
	return (
		<button
			type="button"
			onClick={onClick}
			style={{
				padding: "8px 12px",
				borderRadius: 999,
				border: `1px solid ${active ? C.accent : C.border}`,
				background: active ? C.accentDim : C.surface,
				color: active ? C.accent : C.dimText,
				fontSize: 11,
				cursor: "pointer",
				fontFamily: "inherit",
				letterSpacing: 1,
				fontWeight: 700,
				textTransform: "uppercase",
			}}
		>
			{children}
		</button>
	);
}

function SurvivorPage({ onNavigate, status, httpBase }) {
	const [interactions, setInteractions] = useState([]);
	const [isQuerying, setIsQuerying] = useState(false);

	useEffect(() => {
		const fetchInteractions = () => {
			fetch(`${httpBase}/api/survivors`)
				.then(r => r.json())
				.then(d => { if (d.ok) setInteractions(d.survivors); })
				.catch(e => console.error("Fetch survivors error", e));
		};
		fetchInteractions();
		const id = setInterval(fetchInteractions, 3000);
		return () => clearInterval(id);
	}, [httpBase]);

	return (
		<div style={{ ...styles.app, overflow: "auto" }}>
			<div style={styles.topBar}>
				<div style={styles.logo}><span style={{ fontSize: 22 }}>⬡</span>SURVIVOR INTERACTION</div>
				<div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
					<PageButton onClick={() => onNavigate("landing")}>Home</PageButton>
					<PageButton onClick={() => onNavigate("dashboard")}>Dashboard</PageButton>
					<PageButton onClick={() => onNavigate("map")}>Map</PageButton>
					<PageButton active onClick={() => onNavigate("survivor")}>Survivor</PageButton>
				</div>
			</div>
			<div style={{ padding: 22, display: "grid", gap: 16 }}>
				<div style={{ display: "grid", gridTemplateColumns: "0.4fr 0.6fr", gap: 14 }}>
					<div style={{ ...styles.panel, borderRadius: 24 }}>
						<div style={styles.panelHeader}>TRIAGE STATUS</div>
						<div style={{ ...styles.panelBody, display: "grid", gap: 10 }}>
							<div style={{ color: C.dimText, fontSize: 12, marginBottom: 10 }}>Latest detected survivor data</div>
							<TelRow label="Can Move" value={interactions[0]?.responses?.can_move === false ? "NO" : "YES"} color={interactions[0]?.responses?.can_move === false ? C.red : C.green} />
							<TelRow label="Conscious" value="YES" color={C.green} />
							<TelRow label="Last contact" value={interactions[0]?.timestamp ? new Date(interactions[0].timestamp).toLocaleTimeString() : "N/A"} />
							<div style={{ marginTop: 20, display: "grid", gap: 10 }}>
								<button 
									onClick={() => fetch(`${httpBase}/api/survivors/interaction`, { method: "POST", body: JSON.stringify({ transcript: "Who are you?", responses: {} }), headers: {"Content-Type": "application/json"} })}
									style={{ ...heroPrimaryButton, width: "100%" }}
								>
									COMMAND: INTRODUCE SELF
								</button>
								<button 
									onClick={() => fetch(`${httpBase}/api/survivors/interaction`, { method: "POST", body: JSON.stringify({ transcript: "Are you injured?", responses: {} }), headers: {"Content-Type": "application/json"} })}
									style={{ ...heroSecondaryButton, width: "100%" }}
								>
									TRIAGE: INJURY CHECK
								</button>
								<button 
									onClick={() => fetch(`${httpBase}/api/survivors/interaction`, { method: "POST", body: JSON.stringify({ transcript: "Can you move?", responses: {} }), headers: {"Content-Type": "application/json"} })}
									style={{ ...heroSecondaryButton, width: "100%" }}
								>
									TRIAGE: MOBILITY CHECK
								</button>
							</div>
						</div>
					</div>
					<div style={{ ...styles.panel, borderRadius: 24 }}>
						<div style={styles.panelHeader}>CONVERSATION LOG</div>
						<div style={{ ...styles.panelBody, padding: 0, maxHeight: 600, overflowY: "auto" }}>
							{interactions.map(item => (
								<div key={item.id} style={{ padding: 16, borderBottom: `1px solid ${C.border}` }}>
									<div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
										<span style={{ fontSize: 10, color: C.accent, fontWeight: 700 }}>SURVIVOR ID: {item.id}</span>
										<span style={{ fontSize: 10, color: C.dimText }}>{new Date(item.timestamp).toLocaleString()}</span>
									</div>
									<div style={{ background: C.surface, padding: 12, borderRadius: 12, marginBottom: 8 }}>
										<div style={{ fontSize: 10, color: C.dimText, marginBottom: 4 }}>TRANSCRIPT</div>
										<div style={{ fontSize: 14, color: C.text }}>"{item.transcript}"</div>
									</div>
									{item.responses && (
										<div style={{ display: "flex", gap: 6 }}>
											{Object.entries(item.responses).map(([k, v]) => (
												<Pill key={k} color={v === false ? C.red : C.green} bg={v === false ? "#2a1010" : "#102a10"}>{k}: {String(v)}</Pill>
											))}
										</div>
									)}
								</div>
							)).reverse()}
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}

function HeroStat({ label, value, tone = C.text }) {
	return (
		<div style={{ background: "linear-gradient(180deg, rgba(22,27,34,0.96), rgba(16,19,24,0.98))", border: `1px solid rgba(255,255,255,0.06)`, borderRadius: 18, padding: 18, minHeight: 104, boxShadow: "0 16px 40px rgba(0,0,0,0.18)" }}>
			<div style={{ fontSize: 10, color: C.dimText, letterSpacing: 1.6, textTransform: "uppercase", marginBottom: 6 }}>{label}</div>
			<div style={{ color: tone, fontSize: 24, fontWeight: 800, lineHeight: 1.05 }}>{value}</div>
		</div>
	);
}

function OsintFinderPage({ onNavigate }) {
	const [query, setQuery] = useState("");
	const [isSearching, setIsSearching] = useState(false);
	const [results, setResults] = useState(null);
	const [error, setError] = useState(null);

	const runSearch = useCallback(async () => {
		if (!query.trim()) return;
		setIsSearching(true);
		setError(null);
		setResults(null);
		try {
			const payload = {
				token: OSINT_API_TOKEN,
				request: query,
				limit: 100,
				lang: "en",
				type: "json",
			};

			const response = await fetch(OSINT_API_URL, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});

			const data = await response.json();
			if (data.error) {
				setError(`API Error ${data.error}: Please try again later`);
			} else {
				setResults(data);
			}
		} catch (err) {
			setError(`Connection Error: ${err.message}`);
		} finally {
			setIsSearching(false);
		}
	}, [query]);

	return (
		<div style={{ ...styles.app, overflow: "auto" }}>
			<div style={styles.topBar}>
				<div style={styles.logo}>
					<span style={{ fontSize: 22 }}>⬡</span>
					OSINT FINDER
					<span style={{ color: C.dimText, fontWeight: 400, fontSize: 12 }}>VICTIM DATA COLLECTION</span>
				</div>
				<div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
					<PageButton onClick={() => onNavigate("landing")}>Home</PageButton>
					<PageButton onClick={() => onNavigate("dashboard")}>Dashboard</PageButton>
					<PageButton onClick={() => onNavigate("map")}>Map</PageButton>
					<PageButton onClick={() => onNavigate("archive")}>Archive</PageButton>
					<PageButton active onClick={() => onNavigate("osint")}>OSINT</PageButton>
				</div>
			</div>

			<div style={{ padding: 20, display: "grid", gap: 16, maxWidth: 1400, margin: "0 auto", width: "100%" }}>
				<div style={{ ...styles.panel }}>
					<div style={styles.panelHeader}>VICTIM DATA COLLECTION</div>
					<div style={{ ...styles.panelBody, display: "grid", gap: 12 }}>
						<div style={{ color: C.dimText, fontSize: 12, lineHeight: 1.6 }}>
							Use a single data point (email, phone, or name) to retrieve linked victim records.
							Results are returned by the OSINT database and grouped by source.
						</div>
						<div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10 }}>
							<input
								type="text"
								value={query}
								onChange={(e) => setQuery(e.target.value)}
								onKeyDown={(e) => e.key === "Enter" && runSearch()}
								placeholder="victim email, phone, or name"
								style={{
									padding: "10px 12px",
									borderRadius: 10,
									border: `1px solid ${C.border}`,
									background: C.surface,
									color: C.text,
									fontFamily: "inherit",
								}}
							/>
							<button
								onClick={runSearch}
								disabled={!query || isSearching}
								style={{
									padding: "10px 16px",
									borderRadius: 10,
									border: `1px solid ${C.accent}`,
									background: C.accentDim,
									color: C.accent,
									fontFamily: "inherit",
									fontWeight: 700,
									letterSpacing: 1,
									textTransform: "uppercase",
									cursor: "pointer",
								}}
							>
								{isSearching ? "Searching..." : "Run OSINT"}
							</button>
						</div>
					</div>
				</div>

				{isSearching && (
					<div style={{ ...styles.panel }}>
						<div style={styles.panelHeader}>SEARCH IN PROGRESS</div>
						<div style={{ ...styles.panelBody, color: C.dimText }}>
							Querying OSINT sources for: <strong style={{ color: C.text }}>{query}</strong>
						</div>
					</div>
				)}

				{error && !isSearching && (
					<div style={{ ...styles.panel, border: `1px solid ${C.red}` }}>
						<div style={styles.panelHeader}>SEARCH ERROR</div>
						<div style={{ ...styles.panelBody, color: C.red }}>{error}</div>
					</div>
				)}

				{results && !isSearching && !error && (
					<div style={{ display: "grid", gap: 12 }}>
						<div style={{ ...styles.panel }}>
							<div style={styles.panelHeader}>RESULT SUMMARY</div>
							<div style={{ ...styles.panelBody, display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
								<div style={{ padding: 12, border: `1px solid ${C.border}`, borderRadius: 12 }}>
									<div style={{ color: C.dimText, fontSize: 10, letterSpacing: 1.2 }}>DATABASES</div>
									<div style={{ fontSize: 22, fontWeight: 800 }}>{results.NumOfDatabase ?? 0}</div>
								</div>
								<div style={{ padding: 12, border: `1px solid ${C.border}`, borderRadius: 12 }}>
									<div style={{ color: C.dimText, fontSize: 10, letterSpacing: 1.2 }}>RECORDS</div>
									<div style={{ fontSize: 22, fontWeight: 800 }}>{results.NumOfResults ?? 0}</div>
								</div>
								<div style={{ padding: 12, border: `1px solid ${C.border}`, borderRadius: 12 }}>
									<div style={{ color: C.dimText, fontSize: 10, letterSpacing: 1.2 }}>SEARCH TIME</div>
									<div style={{ fontSize: 22, fontWeight: 800 }}>{results["search time"]?.toFixed?.(3) ?? "0.000"}s</div>
								</div>
								<div style={{ padding: 12, border: `1px solid ${C.border}`, borderRadius: 12 }}>
									<div style={{ color: C.dimText, fontSize: 10, letterSpacing: 1.2 }}>REQUESTS LEFT</div>
									<div style={{ fontSize: 22, fontWeight: 800 }}>{results.free_requests_left ?? "—"}</div>
								</div>
							</div>
						</div>

						{(!results.List || results.NumOfResults === 0) && (
							<div style={{ ...styles.panel, border: `1px solid ${C.green}` }}>
								<div style={styles.panelHeader}>NO RECORDS FOUND</div>
								<div style={{ ...styles.panelBody, color: C.dimText }}>
									No linked victim records were found for this query.
								</div>
							</div>
						)}

						{results.List && results.NumOfResults > 0 && (
							<div style={{ display: "grid", gap: 12 }}>
								{Object.entries(results.List).map(([dbName, dbData]) => (
									<div key={dbName} style={{ ...styles.panel }}>
										<div style={styles.panelHeader}>{dbName}</div>
										<div style={{ ...styles.panelBody, display: "grid", gap: 10 }}>
											{dbData.InfoLeak && (
												<div style={{ color: C.yellow, fontSize: 12 }}>{dbData.InfoLeak}</div>
											)}
											{dbData.Data?.map((entry, entryIdx) => (
												<div key={`${dbName}-${entryIdx}`} style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 12, display: "grid", gap: 8 }}>
													<div style={{ color: C.dimText, fontSize: 10, letterSpacing: 1.2 }}>
														RECORD #{entryIdx + 1}
													</div>
													<div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
														{Object.entries(entry).map(([fieldName, fieldValue]) => {
															if (!fieldValue || fieldValue === "null") return null;
															const fieldType = getOsintFieldType(fieldName);
															const color =
																fieldType === "sensitive"
																	? C.red
																	: fieldType === "contact"
																		? C.accent
																		: fieldType === "identity"
																			? C.green
																			: C.text;
																const value = maskOsintValue(fieldValue, fieldType);
																return (
																	<div key={`${dbName}-${entryIdx}-${fieldName}`}>
																		<div style={{ color: C.dimText, fontSize: 10, letterSpacing: 1.1 }}>
																			{formatOsintFieldName(fieldName)}
																		</div>
																		<div style={{ color, fontSize: 12, fontWeight: 700, wordBreak: "break-word" }}>
																			{value}
																		</div>
																	</div>
																);
															})}
													</div>
												</div>
											))}
										</div>
									</div>
								))}
							</div>
						)}
					</div>
				)}
			</div>
		</div>
	);
}

function LandingPage({ onNavigate, telemetry, status, telemetryArchive, pathData, alerts }) {
	const quickStats = useMemo(() => {
		const archive = Array.isArray(telemetryArchive) ? telemetryArchive : [];
		const latest = archive[archive.length - 1] || telemetry || {};
		const avgBattery = archive.length
			? archive.reduce((sum, item) => sum + (Number(item?.estV) || 0), 0) / archive.length
			: Number(latest?.estV) || 0;
		return {
			samples: archive.length,
			victims: status?.victim_count || 0,
			distanceM: ((pathData?.total_dist_cm || latest?.distTotal || 0) / 100).toFixed(1),
			battery: Number.isFinite(avgBattery) && avgBattery ? avgBattery.toFixed(1) : latest?.estV?.toFixed?.(1) || "—",
		};
	}, [pathData, status, telemetry, telemetryArchive]);

	return (
		<div style={{ ...styles.app, overflow: "auto" }}>
			<div style={styles.topBar}>
				<div style={styles.logo}>
					<span style={{ fontSize: 22 }}>⬡</span>
					RESCUE ROVER
					<span style={{ color: C.dimText, fontWeight: 400, fontSize: 12 }}>MISSION CONTROL</span>
				</div>
				<div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
					<PageButton active onClick={() => onNavigate("landing")}>Home</PageButton>
					<PageButton onClick={() => onNavigate("dashboard")}>Dashboard</PageButton>
					<PageButton onClick={() => onNavigate("map")}>Map</PageButton>
					<PageButton onClick={() => onNavigate("survivor")}>Survivor</PageButton>
					<PageButton onClick={() => onNavigate("archive")}>Archive</PageButton>
					<PageButton onClick={() => onNavigate("osint")}>OSINT</PageButton>
				</div>
			</div>
			<div style={{ padding: 16, maxWidth: 1400, width: "100%", margin: "0 auto" }}>
				<div style={{ background: `linear-gradient(135deg, ${C.surface}, ${C.panel})`, border: `1px solid ${C.border}`, borderRadius: 20, padding: 22, marginBottom: 12, boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }}>
					<div style={{ color: C.accent, letterSpacing: 2, fontSize: 11, textTransform: "uppercase" }}>Live Rover Operations</div>
					<h1 style={{ margin: "10px 0 8px", fontSize: 40, lineHeight: 1.05, color: C.heading }}>
						Satellite-grade mission tracking for rover telemetry, victims, and path history.
					</h1>
					<p style={{ maxWidth: 860, color: C.dimText, fontSize: 14, lineHeight: 1.6 }}>
						The dashboard stores incoming telemetry, plots odometry on a satellite map, keeps a searchable archive, and surfaces mission controls, camera, and alerts in one place.
					</p>
					<div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
						<button onClick={() => onNavigate("dashboard")} style={heroPrimaryButton}>Open Dashboard</button>
						<button onClick={() => onNavigate("map")} style={heroSecondaryButton}>Open Satellite Map</button>
					</div>
				</div>

				<div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10, marginBottom: 12 }}>
					<HeroStat label="Telemetry samples" value={quickStats.samples} tone={C.blue} />
					<HeroStat label="Victims located" value={quickStats.victims} tone={C.yellow} />
					<HeroStat label="Total distance" value={`${quickStats.distanceM} m`} tone={C.green} />
					<HeroStat label="Average battery" value={`${quickStats.battery} V`} tone={C.accent} />
				</div>

				<div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 10 }}>
					<div style={{ ...styles.panel, borderRadius: 20 }}>
						<div style={styles.panelHeader}>MISSION HIGHLIGHTS</div>
						<div style={{ ...styles.panelBody, display: "grid", gap: 8 }}>
							{[
								"Stored telemetry archive with trend charts",
								"Satellite map with rover path and victim markers",
								"Camera stream and manual command controls",
								"Alert feed with watchdog events",
							].map((item) => (
								<div key={item} style={{ padding: 10, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10 }}>{item}</div>
							))}
						</div>
					</div>
					<div style={{ ...styles.panel, borderRadius: 20 }}>
						<div style={styles.panelHeader}>STATUS SNAPSHOT</div>
						<div style={{ ...styles.panelBody, display: "grid", gap: 10 }}>
							<TelRow label="Pi" value={status?.pi_connected ? "ONLINE" : "OFFLINE"} color={status?.pi_connected ? C.green : C.red} />
							<TelRow label="Rover" value={status?.rover_state || "STP"} />
							<TelRow label="Alerts" value={alerts?.length || 0} />
							<TelRow label="Mission active" value={status?.mission_active ? "YES" : "NO"} />
							<TelRow label="Camera" value="LIVE MJPEG" />
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}

function TelemetryArchivePage({ onNavigate, telemetryArchive, telemetry, status }) {
	const history = Array.isArray(telemetryArchive) ? telemetryArchive : [];
	const latest = history[history.length - 1] || telemetry || {};
	const stats = useMemo(() => {
		const batteryValues = history.map((item) => Number(item?.estV)).filter((value) => Number.isFinite(value));
		return {
			total: history.length,
			minBatt: batteryValues.length ? Math.min(...batteryValues).toFixed(1) : "—",
			maxBatt: batteryValues.length ? Math.max(...batteryValues).toFixed(1) : "—",
			latestState: latest?.state || "STP",
		};
	}, [history, latest]);

	const exportJson = () => {
		const blob = new Blob([JSON.stringify(history, null, 2)], { type: "application/json" });
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.href = url;
		link.download = "telemetry-archive.json";
		link.click();
		URL.revokeObjectURL(url);
	};

	const exportCsv = () => {
		const header = ["ms", "x", "y", "heading", "dist", "distTotal", "estV", "state", "flags"].join(",");
		const rows = history.map((item) => [
			item?.ms ?? "",
			item?.abs_x ?? item?.x ?? "",
			item?.abs_y ?? item?.y ?? "",
			item?.heading ?? "",
			item?.dist ?? "",
			item?.distTotal ?? "",
			item?.estV ?? "",
			item?.state ?? "",
			item?.flags ?? "",
		].join(","));
		const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.href = url;
		link.download = "telemetry-archive.csv";
		link.click();
		URL.revokeObjectURL(url);
	};

	return (
		<div style={{ ...styles.app, overflow: "auto" }}>
			<div style={styles.topBar}>
				<div style={styles.logo}><span style={{ fontSize: 22 }}>⬡</span>TELEMETRY ARCHIVE</div>
				<div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
					<PageButton onClick={() => onNavigate("landing")}>Home</PageButton>
					<PageButton onClick={() => onNavigate("dashboard")}>Dashboard</PageButton>
					<PageButton onClick={() => onNavigate("map")}>Map</PageButton>
					<PageButton active onClick={() => onNavigate("archive")}>Archive</PageButton>
					<PageButton onClick={() => onNavigate("osint")}>OSINT</PageButton>
				</div>
			</div>
			<div style={{ padding: 22, display: "grid", gap: 16 }}>
				<div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
					<div>
						<div style={{ color: C.dimText, fontSize: 11, letterSpacing: 1.5, textTransform: "uppercase" }}>Stored telemetry</div>
						<div style={{ fontSize: 28, fontWeight: 800, color: C.heading }}>Visualize and export the mission log</div>
					</div>
					<div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
						<button onClick={exportJson} style={heroPrimaryButton}>Download JSON</button>
						<button onClick={exportCsv} style={heroSecondaryButton}>Download CSV</button>
					</div>
				</div>

				<div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>
					<HeroStat label="Samples stored" value={stats.total} tone={C.blue} />
					<HeroStat label="Latest rover state" value={stats.latestState} tone={C.accent} />
					<HeroStat label="Battery min/max" value={`${stats.minBatt} / ${stats.maxBatt}`} tone={C.green} />
					<HeroStat label="Victims" value={status?.victim_count || 0} tone={C.yellow} />
				</div>

				<div style={{ ...styles.panel, borderRadius: 24, minHeight: 260 }}>
					<div style={styles.panelHeader}>TREND VIEW</div>
					<div style={{ flex: 1, minHeight: 220 }}>
						<TelemetryChart history={history} />
					</div>
				</div>

				<div style={{ ...styles.panel, borderRadius: 24 }}>
					<div style={styles.panelHeader}>LATEST SAMPLES</div>
					<div style={{ ...styles.panelBody, padding: 10, maxHeight: 420 }}>
						<table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
							<thead>
								<tr style={{ color: C.dimText, textAlign: "left" }}>
									<th style={archiveCell}>Time</th>
									<th style={archiveCell}>X</th>
									<th style={archiveCell}>Y</th>
									<th style={archiveCell}>Heading</th>
									<th style={archiveCell}>Dist</th>
									<th style={archiveCell}>Batt</th>
									<th style={archiveCell}>State</th>
									<th style={archiveCell}>Flags</th>
								</tr>
							</thead>
							<tbody>
								{history.slice(-40).reverse().map((item, index) => (
									<tr key={`${item?.ms ?? index}-${index}`} style={{ borderTop: `1px solid ${C.border}` }}>
										<td style={archiveCell}>{item?.ms != null ? `${(item.ms / 1000).toFixed(1)}s` : "—"}</td>
										<td style={archiveCell}>{Number(item?.abs_x ?? item?.x ?? NaN).toFixed?.(1) ?? "—"}</td>
										<td style={archiveCell}>{Number(item?.abs_y ?? item?.y ?? NaN).toFixed?.(1) ?? "—"}</td>
										<td style={archiveCell}>{Number(item?.heading ?? NaN).toFixed?.(1) ?? "—"}</td>
										<td style={archiveCell}>{item?.dist === 999 ? "OOR" : item?.dist ?? "—"}</td>
										<td style={archiveCell}>{Number(item?.estV ?? NaN).toFixed?.(1) ?? "—"}</td>
										<td style={archiveCell}>{item?.state ?? "—"}</td>
										<td style={archiveCell}>{item?.flags ?? "—"}</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	);
}

function MapPage({
	onNavigate,
	pathData,
	telemetry,
	telemetryHistory,
	mapOrigin,
	setMapOrigin,
	status,
	httpBase,
	sendMode,
}) {
	const routeState = pathData?.route && typeof pathData.route === "object" ? pathData.route : { waypoints: [], status: "idle", paused: false, active_index: 0, name: "Patrol Route" };
	const backendWaypoints = Array.isArray(routeState.waypoints) ? routeState.waypoints : [];
	const [plannerMode, setPlannerMode] = useState("waypoint");
	const [routeName, setRouteName] = useState(routeState.name || "Patrol Route");
	const [draftWaypoints, setDraftWaypoints] = useState(backendWaypoints);
	const [isSaving, setIsSaving] = useState(false);
	const [waypointLat, setWaypointLat] = useState("");
	const [waypointLng, setWaypointLng] = useState("");

	useEffect(() => {
		if (backendWaypoints.length === 0 || draftWaypoints.length > 0) return;
		setDraftWaypoints(backendWaypoints);
	}, [backendWaypoints, draftWaypoints.length]);

	useEffect(() => {
		if (routeState.name && !routeName) {
			setRouteName(routeState.name);
		}
	}, [routeName, routeState.name]);

	const postJson = useCallback(async (url, body) => {
		const response = await fetch(`${httpBase}${url}`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		});
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}`);
		}
		return response.json();
	}, [httpBase]);

	const updateRoute = useCallback(async (action, overrides = {}) => {
		const route = {
			name: routeName.trim() || "Patrol Route",
			waypoints: draftWaypoints,
			status: overrides.status || routeState.status || "idle",
			paused: Boolean(overrides.paused ?? routeState.paused ?? false),
			active_index: Number.isFinite(overrides.active_index) ? overrides.active_index : routeState.active_index || 0,
		};

		setIsSaving(true);
		try {
			await postJson("/api/route", { action, route });
			if (action === "start") {
				await sendMode?.("follow-path");
			}
			if (action === "pause") {
				await sendMode?.("hold-position");
			}
			if (action === "stop") {
				await sendMode?.("emergency-stop");
			}
		} finally {
			setIsSaving(false);
		}
	}, [draftWaypoints, postJson, routeName, routeState.active_index, routeState.paused, routeState.status, sendMode]);

	const handleWaypointAdd = useCallback((latlng) => {
		const next = [
			...draftWaypoints,
			{ lat: Number(latlng.lat.toFixed(6)), lng: Number(latlng.lng.toFixed(6)) },
		];
		setDraftWaypoints(next);
		postJson("/api/route", {
			action: "set",
			route: {
				name: routeName.trim() || "Patrol Route",
				waypoints: next,
				status: "idle",
				paused: false,
				active_index: 0,
			},
		}).catch(() => {});
	}, [draftWaypoints, postJson, routeName]);

	const handleWaypointAddManual = useCallback(() => {
		const lat = Number.parseFloat(waypointLat);
		const lng = Number.parseFloat(waypointLng);
		if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
		const next = [...draftWaypoints, { lat, lng }];
		setDraftWaypoints(next);
		setWaypointLat("");
		setWaypointLng("");
		postJson("/api/route", {
			action: "set",
			route: {
				name: routeName.trim() || "Patrol Route",
				waypoints: next,
				status: "idle",
				paused: false,
				active_index: 0,
			},
		}).catch(() => {});
	}, [draftWaypoints, postJson, routeName, waypointLat, waypointLng]);

	const clearRoute = useCallback(async () => {
		setDraftWaypoints([]);
		await updateRoute("clear", { status: "idle", paused: false, active_index: 0 });
	}, [updateRoute]);

	return (
		<div style={{ ...styles.app, overflow: "auto" }}>
			<div style={styles.topBar}>
				<div style={styles.logo}><span style={{ fontSize: 22 }}>⬡</span>SATELLITE MAP</div>
				<div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
					<PageButton onClick={() => onNavigate("landing")}>Home</PageButton>
					<PageButton onClick={() => onNavigate("dashboard")}>Dashboard</PageButton>
					<PageButton active onClick={() => onNavigate("map")}>Map</PageButton>
					<PageButton onClick={() => onNavigate("archive")}>Archive</PageButton>
					<PageButton onClick={() => onNavigate("osint")}>OSINT</PageButton>
				</div>
			</div>
			<div style={{ padding: 20, display: "grid", gap: 14 }}>
				<div style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 14, alignItems: "start" }}>
					<div style={{ display: "grid", gap: 14 }}>
						<div style={{ ...styles.panel, borderRadius: 24 }}>
							<SatelliteMapPanel
								pathData={pathData}
								telemetry={telemetry}
								telemetryHistory={telemetryHistory}
								origin={mapOrigin}
								setOrigin={setMapOrigin}
								plannerMode={plannerMode}
								onWaypointAdd={handleWaypointAdd}
							/>
						</div>
						<div style={{ ...styles.panel, borderRadius: 24 }}>
							<div style={styles.panelHeader}>MISSION SNAPSHOT</div>
							<div style={{ ...styles.panelBody, display: "grid", gap: 10 }}>
								<TelRow label="Pi" value={status?.pi_connected ? "ONLINE" : "OFFLINE"} color={status?.pi_connected ? C.green : C.red} />
								<TelRow label="Rover state" value={status?.rover_state || "STP"} />
								<TelRow label="Victims" value={status?.victim_count || 0} color={status?.victim_count ? C.yellow : C.text} />
								<TelRow label="Camera" value="LIVE" />
								<TelRow label="Planner mode" value={plannerMode.toUpperCase()} />
							</div>
						</div>
						<div style={{ ...styles.panel, borderRadius: 24 }}>
							<div style={styles.panelHeader}>MARKERS</div>
							<div style={{ ...styles.panelBody, display: "grid", gap: 8 }}>
								<div style={markerLegendItem}><span style={{ color: C.green }}>●</span> Rover</div>
								<div style={markerLegendItem}><span style={{ color: C.accent }}>━</span> Live path</div>
								<div style={markerLegendItem}><span style={{ color: C.blue }}>●</span> Waypoint</div>
								<div style={markerLegendItem}><span style={{ color: C.yellow }}>●</span> Victim</div>
							</div>
						</div>
					</div>
					<div style={{ display: "grid", gap: 14 }}>
						<div style={{ ...styles.panel, borderRadius: 24 }}>
							<div style={styles.panelHeader}>ROUTE PLANNER</div>
							<div style={{ ...styles.panelBody, display: "grid", gap: 10 }}>
								<div style={{ color: C.dimText, fontSize: 11, lineHeight: 1.6 }}>
										Choose <strong>Waypoint</strong> mode and click the map to build a patrol path.
								</div>
								<label style={{ display: "grid", gap: 4, fontSize: 10, color: C.dimText }}>
									Route name
									<input value={routeName} onChange={(e) => setRouteName(e.target.value)} style={mapInputStyle} placeholder="Patrol Route" />
								</label>
								<div style={{ display: "grid", gap: 6, gridTemplateColumns: "1fr 1fr auto", alignItems: "end" }}>
									<label style={{ display: "grid", gap: 4, fontSize: 10, color: C.dimText }}>
										Waypoint Lat
										<input
											type="number"
											step="any"
											value={waypointLat}
											onChange={(e) => setWaypointLat(e.target.value)}
											placeholder="e.g. 18.5204"
											style={mapInputStyle}
										/>
									</label>
									<label style={{ display: "grid", gap: 4, fontSize: 10, color: C.dimText }}>
										Waypoint Lng
										<input
											type="number"
											step="any"
											value={waypointLng}
											onChange={(e) => setWaypointLng(e.target.value)}
											placeholder="e.g. 73.8567"
											style={mapInputStyle}
										/>
									</label>
									<button type="button" onClick={handleWaypointAddManual} style={{ ...heroSecondaryButton, padding: "8px 10px", borderRadius: 12 }}>
										Add waypoint
									</button>
								</div>
								<div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
									<Vb active={plannerMode === "waypoint"} onClick={() => setPlannerMode("waypoint")}>Waypoint</Vb>
									<Vb active={plannerMode === "inspect"} onClick={() => setPlannerMode("inspect")}>Inspect</Vb>
								</div>
								<div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
									<button type="button" disabled={isSaving} onClick={() => updateRoute("set")} style={heroPrimaryButton}>Save route</button>
									<button type="button" disabled={isSaving} onClick={() => updateRoute("start", { status: "active", paused: false, active_index: 0 })} style={heroSecondaryButton}>Start patrol</button>
									<button type="button" disabled={isSaving} onClick={() => updateRoute("pause", { status: "paused", paused: true })} style={heroSecondaryButton}>Pause</button>
									<button type="button" disabled={isSaving} onClick={() => updateRoute("resume", { status: "active", paused: false })} style={heroSecondaryButton}>Resume</button>
									<button type="button" disabled={isSaving} onClick={() => updateRoute("skip", { status: "active", paused: false, active_index: Number(routeState.active_index || 0) + 1 })} style={heroSecondaryButton}>Skip</button>
									<button type="button" disabled={isSaving} onClick={clearRoute} style={{ ...heroSecondaryButton, color: C.red, borderColor: C.red }}>Clear</button>
								</div>
								<div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: C.dimText }}>
									<Pill color={C.blue} bg="#10263a">{draftWaypoints.length} waypoints</Pill>
									<Pill color={C.green} bg="#0f2414">{routeState.status || "idle"}</Pill>
								</div>
							</div>
						</div>
						<div style={{ ...styles.panel, borderRadius: 24 }}>
							<div style={styles.panelHeader}>AUTONOMY MODES</div>
							<div style={{ ...styles.panelBody, display: "grid", gap: 8 }}>
								{["follow-path", "search-grid", "return-to-home", "hold-position", "emergency-stop"].map((mode) => (
									<button
										key={mode}
										type="button"
										onClick={() => sendMode?.(mode)}
										style={{
											padding: "10px 12px",
											borderRadius: 12,
											border: `1px solid ${status?.motion_mode === mode && status?.motion_active ? C.accent : C.border}`,
											background: status?.motion_mode === mode && status?.motion_active ? C.accentDim : C.surface,
											color: status?.motion_mode === mode && status?.motion_active ? C.accent : C.text,
											fontFamily: "inherit",
											fontWeight: 700,
											letterSpacing: 1,
											textTransform: "uppercase",
											cursor: "pointer",
										}}
									>
										{mode}
									</button>
								))}
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}

const heroPrimaryButton = {
	padding: "12px 16px",
	borderRadius: 999,
	border: `1px solid ${C.accent}`,
	background: C.accentDim,
	color: C.accent,
	fontSize: 12,
	cursor: "pointer",
	fontFamily: "inherit",
	letterSpacing: 1,
	fontWeight: 700,
	textTransform: "uppercase",
};

const heroSecondaryButton = {
	...heroPrimaryButton,
	background: C.surface,
	border: `1px solid ${C.border}`,
	color: C.text,
};

const archiveCell = {
	padding: "8px 6px",
	borderBottom: `1px solid ${C.border}`,
	whiteSpace: "nowrap",
	fontVariantNumeric: "tabular-nums",
};

const markerLegendItem = {
	display: "flex",
	alignItems: "center",
	gap: 8,
	padding: 10,
	background: C.surface,
	border: `1px solid ${C.border}`,
	borderRadius: 12,
	fontSize: 12,
};

// ─── Main app ───────────────────────────────────────────────────────────────

function App() {
	const {
		connected,
		telemetry,
		telemetryArchive,
		pathData,
		alerts,
		status,
		sendCommand,
		sendMode,
		httpBase,
	} = useRoverWebSocket();
	const [telHistory, setTelHistory] = useState([]);
	const [elapsed, setElapsed] = useState(0);
	const [isMobile, setIsMobile] = useState(false);
	const [page, setPage] = useState(() => readStoredPage());
	const [mapOrigin, setMapOrigin] = useState(() => readStoredMapOrigin());
	const startRef = useRef(null);
	const supportsAuto = Boolean(status?.capabilities?.commands?.includes("A"));
	const supportedModes = status?.capabilities?.modes || [];
	const supportsModes = supportedModes.length > 0;
	const telemetryHistory = telemetryArchive?.length ? telemetryArchive : telHistory;
	const navigate = useCallback((nextPage) => setPage(nextPage), []);

	useEffect(() => {
		const onResize = () => setIsMobile(window.innerWidth < 900);
		onResize();
		window.addEventListener("resize", onResize);
		return () => window.removeEventListener("resize", onResize);
	}, []);

	// Track telemetry history for charts
	useEffect(() => {
		if (!telemetry) return;
		if (!startRef.current) startRef.current = Date.now();
		setTelHistory((prev) => [...prev.slice(-200), telemetry]);
	}, [telemetry]);

	// Mission timer
	useEffect(() => {
		if (!status.mission_active) return;
		if (!startRef.current) startRef.current = Date.now();
		const id = setInterval(() => {
			setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
		}, 1000);
		return () => clearInterval(id);
	}, [status.mission_active]);

	useEffect(() => {
		if (typeof window === "undefined") return;
		window.localStorage.setItem(LOCAL_STORAGE_MAP_ORIGIN_KEY, JSON.stringify(mapOrigin));
	}, [mapOrigin]);

	useEffect(() => {
		if (typeof window === "undefined") return;
		window.localStorage.setItem(LOCAL_STORAGE_PAGE_KEY, page);
	}, [page]);

	const fmtTime = (s) =>
		`${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

	if (page === "landing") {
		return (
			<LandingPage
				onNavigate={navigate}
				telemetry={telemetry}
				status={status}
				telemetryArchive={telemetryHistory}
				pathData={pathData}
				alerts={alerts}
			/>
		);
	}

	if (page === "archive") {
		return (
			<TelemetryArchivePage
				onNavigate={navigate}
				telemetryArchive={telemetryHistory}
				telemetry={telemetry}
				status={status}
			/>
		);
	}

	if (page === "map") {
		return (
			<MapPage
				onNavigate={navigate}
				pathData={pathData}
				telemetry={telemetry}
				telemetryHistory={telemetryHistory}
				mapOrigin={mapOrigin}
				setMapOrigin={setMapOrigin}
				status={status}
				httpBase={httpBase}
				sendMode={sendMode}
			/>
		);
	}

	if (page === "osint") {
		return <OsintFinderPage onNavigate={navigate} />;
	}

	if (page === "survivor") {
		return (
			<SurvivorPage
				onNavigate={navigate}
				status={status}
				httpBase={httpBase}
			/>
		);
	}

	return (
		<div style={styles.app}>
			{/* Top bar */}
			<div style={styles.topBar}>
				<div style={styles.logo}>
					<span style={{ fontSize: 22 }}>⬡</span>
					RESCUE ROVER
					<span style={{ color: C.dimText, fontWeight: 400, fontSize: 12 }}>
						MISSION CONTROL
					</span>
				</div>
				<div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
					<PageButton active={page === "landing"} onClick={() => navigate("landing")}>Home</PageButton>
					<PageButton active={page === "dashboard"} onClick={() => navigate("dashboard")}>Dashboard</PageButton>
					<PageButton active={page === "map"} onClick={() => navigate("map")}>Map</PageButton>
					<PageButton active={page === "survivor"} onClick={() => navigate("survivor")}>Survivor</PageButton>
					<PageButton active={page === "archive"} onClick={() => navigate("archive")}>Archive</PageButton>
					<PageButton active={page === "osint"} onClick={() => navigate("osint")}>OSINT</PageButton>
				</div>

				<div
					style={{
						display: "flex",
						gap: 8,
						alignItems: "center",
						marginLeft: 12,
					}}
				>
					<Pill
						color={connected ? C.green : C.red}
						bg={connected ? "#0e2e10" : "#300"}
					>
						{connected ? "● WS" : "○ DISC"}
					</Pill>
					<Pill
						color={status.pi_connected ? C.green : C.dimText}
						bg={C.surface}
					>
						PI {status.pi_connected ? "ONLINE" : "OFFLINE"}
					</Pill>
					{status.motion_active && status.motion_mode && (
						<Pill color={C.accent} bg={C.accentDim}>
							MODE {String(status.motion_mode).toUpperCase()}
						</Pill>
					)}
					{supportsAuto && status.auto_mode && (
						<Pill color={C.accent} bg={C.accentDim}>
							AUTO
						</Pill>
					)}
				</div>

				<div
					style={{ marginLeft: "auto", display: "flex", gap: 20, fontSize: 12 }}
				>
					<span>
						<span style={{ color: C.dimText }}>MISSION </span>
						<span style={{ color: C.green, fontWeight: 700 }}>
							{fmtTime(elapsed)}
						</span>
					</span>
					<span>
						<span style={{ color: C.dimText }}>VICTIMS </span>
						<span style={{ color: C.yellow, fontWeight: 700 }}>
							{status.victim_count}
						</span>
					</span>
					<span>
						<span style={{ color: C.dimText }}>DIST </span>
						<span style={{ color: C.text, fontWeight: 700 }}>
							{(
								(pathData?.total_dist_cm || telemetry?.distTotal || 0) / 100
							).toFixed(1)}{" "}
							m
						</span>
					</span>
					<span>
						<span style={{ color: C.dimText }}>STATE </span>
						<StateBadge state={telemetry?.state} />
					</span>
					<span>
						<span style={{ color: C.dimText }}>BATT </span>
						<span
							style={{
								fontWeight: 700,
								color:
									(telemetry?.estV || 12) < 10.8
										? C.red
										: (telemetry?.estV || 12) < 11.2
											? C.yellow
											: C.green,
							}}
						>
							{telemetry?.estV?.toFixed(1) ?? "—"}V
						</span>
					</span>
				</div>
			</div>

			{/* Main grid */}
			<div style={{ ...styles.grid, ...(isMobile ? styles.gridMobile : null) }}>
				{/* Left panel: Telemetry + Controls */}
				<div
					style={{
						...styles.panel,
						gridColumn: "1",
						gridRow: isMobile ? "1" : "1 / 3",
						borderRight: isMobile ? "none" : `1px solid ${C.border}`,
					}}
				>
					<div style={styles.panelHeader}>TELEMETRY</div>
					<div style={{ ...styles.panelBody, fontSize: 12 }}>
						<TelRow
							label="X Position"
							value={telemetry?.abs_x?.toFixed(1) ?? telemetry?.x?.toFixed(1)}
							unit="cm"
						/>
						<TelRow
							label="Y Position"
							value={telemetry?.abs_y?.toFixed(1) ?? telemetry?.y?.toFixed(1)}
							unit="cm"
						/>
						<TelRow
							label="Heading"
							value={telemetry?.heading?.toFixed(1)}
							unit="°"
						/>
						<TelRow
							label="Sonar"
							value={telemetry?.dist === 999 ? "OOR" : telemetry?.dist}
							unit="cm"
							color={telemetry?.dist < 30 ? C.red : C.text}
						/>
						<TelRow
							label="Lap Dist"
							value={telemetry?.distLap?.toFixed(1)}
							unit="cm"
						/>
						<TelRow
							label="Total Dist"
							value={telemetry?.distTotal?.toFixed(1)}
							unit="cm"
						/>
						<TelRow
							label="Est Battery"
							value={telemetry?.estV?.toFixed(1)}
							unit="V"
							color={
								(telemetry?.estV ?? 12) < 10.8
									? C.red
									: (telemetry?.estV ?? 12) < 11.2
										? C.yellow
										: C.green
							}
						/>
						<TelRow label="RPM" value={telemetry?.rpm?.toFixed(1)} />
						<TelRow
							label="AccelY"
							value={telemetry?.accelY?.toFixed(2)}
							unit="m/s²"
						/>
						<TelRow
							label="GyroZ"
							value={telemetry?.gyroZ?.toFixed(2)}
							unit="°/s"
						/>
						<TelRow
							label="Chip Temp"
							value={telemetry?.chipTemp?.toFixed(1)}
							unit="°C"
						/>
						<TelRow
							label="Flags"
							value={telemetry?.flags}
							color={telemetry?.flags === "OK" ? C.green : C.red}
						/>
						<TelRow label="Seq #" value={telemetry?.seq} />
						<TelRow
							label="Uptime"
							value={telemetry?.ms ? (telemetry.ms / 1000).toFixed(0) : "—"}
							unit="s"
						/>
						<TelRow
							label="Victims"
							value={status.victim_count}
							color={status.victim_count > 0 ? C.yellow : C.text}
						/>

						<div style={{ marginTop: 16 }}>
							<div
								style={{
									...styles.panelHeader,
									padding: "6px 0",
									marginBottom: 10,
								}}
							>
								CONTROLS
							</div>
							<ControlPad
								sendCommand={sendCommand}
								status={status}
								supportsAuto={supportsAuto}
							/>
						</div>

						{supportsModes && (
							<div style={{ marginTop: 18 }}>
								<div
									style={{
										...styles.panelHeader,
										padding: "6px 0",
										marginBottom: 10,
									}}
								>
									PATH MODES
								</div>
								<div
									style={{
										display: "grid",
										gridTemplateColumns: "1fr 1fr",
										gap: 6,
									}}
								>
									{supportedModes.map((mode) => (
										<button
											key={mode}
											onClick={() => sendMode(mode)}
											style={{
												padding: "6px 0",
												background:
													status.motion_mode === mode && status.motion_active
														? C.accentDim
														: C.surface,
												border: `1px solid ${
													status.motion_mode === mode && status.motion_active
														? C.accent
														: C.border
												}`,
												borderRadius: 6,
												color:
													status.motion_mode === mode && status.motion_active
														? C.accent
														: C.dimText,
												fontSize: 11,
												cursor: "pointer",
												fontFamily: "inherit",
												letterSpacing: 1,
												fontWeight: 600,
												textTransform: "uppercase",
											}}
										>
											{mode}
										</button>
									))}
									<button
										onClick={() => sendMode("stop")}
										style={{
											gridColumn: "1 / 3",
											padding: "6px 0",
											background: C.surface,
											border: `1px solid ${C.border}`,
											borderRadius: 6,
											color: C.red,
											fontSize: 11,
											cursor: "pointer",
											fontFamily: "inherit",
											letterSpacing: 1,
											fontWeight: 600,
											textTransform: "uppercase",
										}}
									>
										STOP MODE
									</button>
								</div>
							</div>
						)}
					</div>
				</div>

				{/* Center: Path visualization */}
				<div
					style={{
						...styles.panel,
						gridColumn: isMobile ? "1" : "2",
						gridRow: isMobile ? "2" : "1",
					}}
				>
					<SatelliteMapPanel
						pathData={pathData}
						telemetry={telemetry}
						telemetryHistory={telemetryHistory}
						origin={mapOrigin}
						setOrigin={setMapOrigin}
					/>
				</div>

				{/* Bottom: Charts */}
				<div
					style={{
						...styles.panel,
						gridColumn: isMobile ? "1" : "2",
						gridRow: isMobile ? "3" : "2",
					}}
				>
					<div style={styles.panelHeader}>SENSOR GRAPHS — LAST 60 PACKETS</div>
					<div style={{ flex: 1, minHeight: 0 }}>
						<TelemetryChart history={telemetryHistory} />
					</div>
				</div>

				{/* Right: Alerts */}
				<div
					style={{
						gridColumn: isMobile ? "1" : "3 / 4",
						gridRow: isMobile ? "4" : "1 / 2",
					}}
				>
					<AlertsPanel alerts={alerts} />
				</div>

				{/* Right: Camera */}
				<div
					style={{
						gridColumn: isMobile ? "1" : "3 / 4",
						gridRow: isMobile ? "5" : "2 / 3",
					}}
				>
					<CameraPanel src={httpBase ? `${httpBase}/api/camera/stream` : ""} />
				</div>
			</div>
		</div>
	);
}

export default App;
