import React from "react";

export default function LogsPanel({ logs }) {
  const list = Array.isArray(logs) ? logs.slice(0, 80) : [];

  return (
    <div className="panel logs-panel">
      <div className="panel-title">Mission Log</div>
      <div className="logs">
        {list.length === 0 && <div className="log-line">Awaiting events...</div>}
        {list.map((log, idx) => (
          <div className="log-line" key={`${log.message}-${idx}`}>
            [{new Date(log.timestampMs || Date.now()).toLocaleTimeString()}] {log.level || "INFO"} - {log.message}
          </div>
        ))}
      </div>
    </div>
  );
}
