import React, { useEffect } from "react";

const keyMap = {
  w: "F",
  s: "B",
  a: "L",
  d: "R",
  " ": "S",
  ArrowUp: "F",
  ArrowDown: "B",
  ArrowLeft: "L",
  ArrowRight: "R"
};

export default function Controls({ onCommand }) {
  useEffect(() => {
    const handler = (event) => {
      const cmd = keyMap[event.key];
      if (cmd) {
        event.preventDefault();
        onCommand(cmd);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCommand]);

  return (
    <div className="panel controls-panel">
      <div className="panel-title">Controls</div>
      <div className="controls">
        <div></div>
        <button onClick={() => onCommand("F")}>Forward</button>
        <div></div>
        <button onClick={() => onCommand("L")}>Left</button>
        <button className="emergency" onClick={() => onCommand("S")}>Stop</button>
        <button onClick={() => onCommand("R")}>Right</button>
        <div></div>
        <button onClick={() => onCommand("B")}>Reverse</button>
        <div></div>
      </div>
    </div>
  );
}
