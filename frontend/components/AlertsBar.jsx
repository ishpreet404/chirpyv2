import React from "react";

export default function AlertsBar({ alerts, wsConnected, telemetry }) {
  const latestAlerts = Array.isArray(alerts) ? alerts.slice(0, 4) : [];
  const obstacle = telemetry?.obstacle;
  const batteryLow = telemetry?.batteryV > 0 && telemetry?.batteryV <= 10.6;

  return (
    <div className="alerts-bar">
      <div className="alerts-title">Mission Alerts</div>
      <div className="alert-items">
        {obstacle && <div className="alert-item">Obstacle detected</div>}
        {batteryLow && <div className="alert-item">Battery low</div>}
        {latestAlerts.map((alert, idx) => (
          <div className="alert-item" key={`${alert.message}-${idx}`}>
            {alert.message}
          </div>
        ))}
        {!obstacle && !batteryLow && latestAlerts.length === 0 && (
          <div className="alert-item" style={{ background: "rgba(54,245,199,0.18)", borderColor: "rgba(54,245,199,0.6)" }}>
            All clear
          </div>
        )}
      </div>
      <div className="status-pill">
        <span className={`status-dot ${wsConnected ? "ok" : ""}`}></span>
        {wsConnected ? "LIVE" : "DISCONNECTED"}
      </div>
    </div>
  );
}
