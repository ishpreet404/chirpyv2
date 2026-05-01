import React from "react";

function Sparkline({ values, color }) {
  if (!values || values.length === 0) {
    return <svg className="sparkline"></svg>;
  }

  const width = 220;
  const height = 48;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);

  const points = values.map((v, i) => {
    const x = (i / (values.length - 1 || 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`}>
      <polyline points={points.join(" ")} fill="none" stroke={color} strokeWidth="2" />
    </svg>
  );
}

export default function TelemetryPanel({ telemetry, history }) {
  const gpsText = telemetry.gpsFix
    ? `${telemetry.lat.toFixed(5)}, ${telemetry.lon.toFixed(5)}`
    : "NO FIX";

  return (
    <div className="panel telemetry-panel">
      <div className="panel-title">Telemetry</div>
      <div className="telemetry-grid">
        <div className="telemetry-card">
          <h4>Speed (RPM)</h4>
          <span>{telemetry.rpm.toFixed(1)}</span>
          <Sparkline values={history.rpm} color="#36f5c7" />
        </div>
        <div className="telemetry-card">
          <h4>Battery (V)</h4>
          <span>{telemetry.batteryV.toFixed(2)}</span>
          <Sparkline values={history.battery} color="#ff9f1a" />
        </div>
        <div className="telemetry-card">
          <h4>Heading (deg)</h4>
          <span>{telemetry.heading.toFixed(1)}</span>
          <Sparkline values={history.heading} color="#9bd9ff" />
        </div>
        <div className="telemetry-card">
          <h4>Obstacle (cm)</h4>
          <span>{telemetry.distCm}</span>
        </div>
        <div className="telemetry-card">
          <h4>Position (m)</h4>
          <span>{telemetry.x.toFixed(2)}, {telemetry.y.toFixed(2)}</span>
        </div>
        <div className="telemetry-card">
          <h4>GPS</h4>
          <span>{gpsText}</span>
        </div>
      </div>
    </div>
  );
}
