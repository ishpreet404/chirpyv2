import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts';
import { useRoverWebSocket } from './hooks/useRoverWebSocket';

// ─── Design tokens ─────────────────────────────────────────────────────────

const C = {
  bg:       '#0a0c10',
  surface:  '#111418',
  panel:    '#161b22',
  border:   '#21262d',
  accent:   '#e85d2a',     // rescue orange
  accentDim:'#7a2d12',
  green:    '#3fb950',
  yellow:   '#d29922',
  red:      '#f85149',
  blue:     '#58a6ff',
  dimText:  '#8b949e',
  text:     '#e6edf3',
  heading:  '#f0f6fc',
};

const styles = {
  app: {
    background: C.bg,
    minHeight: '100vh',
    color: C.text,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  topBar: {
    background: C.surface,
    borderBottom: `1px solid ${C.border}`,
    padding: '10px 20px',
    display: 'flex',
    alignItems: 'center',
    gap: 20,
    flexShrink: 0,
  },
  logo: {
    color: C.accent,
    fontWeight: 700,
    fontSize: 18,
    letterSpacing: 2,
    textTransform: 'uppercase',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  badge: (color, bg) => ({
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 700,
    color,
    background: bg,
    letterSpacing: 1,
  }),
  grid: {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: '300px 1fr 260px',
    gridTemplateRows: '1fr 220px',
    gap: 1,
    background: C.border,
    overflow: 'hidden',
    minHeight: 0,
  },
  panel: {
    background: C.panel,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  panelHeader: {
    padding: '8px 14px',
    borderBottom: `1px solid ${C.border}`,
    fontSize: 11,
    letterSpacing: 1.5,
    color: C.dimText,
    fontWeight: 600,
    textTransform: 'uppercase',
    flexShrink: 0,
  },
  panelBody: {
    flex: 1,
    overflow: 'auto',
    padding: 14,
    minHeight: 0,
  },
  telRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    padding: '4px 0',
    borderBottom: `1px solid ${C.border}`,
  },
  telLabel: { color: C.dimText, fontSize: 11, letterSpacing: 0.5 },
  telVal: { fontWeight: 600, fontSize: 13, fontVariantNumeric: 'tabular-nums' },
};

// ─── Utility components ─────────────────────────────────────────────────────

function Pill({ children, color = C.dimText, bg = C.surface }) {
  return <span style={styles.badge(color, bg)}>{children}</span>;
}

function TelRow({ label, value, unit = '', color = C.text }) {
  return (
    <div style={styles.telRow}>
      <span style={styles.telLabel}>{label}</span>
      <span style={{ ...styles.telVal, color }}>{value ?? '—'}{unit && <span style={{ color: C.dimText, fontSize: 11 }}> {unit}</span>}</span>
    </div>
  );
}

function StateBadge({ state }) {
  const map = {
    FWD: [C.green,   '#1a3a1e'],
    BCK: [C.yellow,  '#3a2e0e'],
    LFT: [C.blue,    '#0e2233'],
    RGT: [C.blue,    '#0e2233'],
    STP: [C.dimText, C.surface],
  };
  const [fg, bg] = map[state] || [C.dimText, C.surface];
  return <Pill color={fg} bg={bg}>{state || 'STP'}</Pill>;
}

function AlertBadge({ level }) {
  const map = {
    critical: [C.red,    '#300'],
    warning:  [C.yellow, '#330'],
    info:     [C.blue,   '#003'],
  };
  const [fg, bg] = map[level] || [C.dimText, C.surface];
  return <Pill color={fg} bg={bg}>{level.toUpperCase()}</Pill>;
}

// ─── Path Canvas ─────────────────────────────────────────────────────────────

function PathCanvas({ pathData, telemetry }) {
  const canvasRef = useRef(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    // Grid
    ctx.strokeStyle = '#1a1f27';
    ctx.lineWidth = 1;
    for (let x = 0; x < W; x += 30) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += 30) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    const segments = pathData?.segments || [];
    const obstacles = pathData?.obstacles || [];
    const victims = pathData?.victims || [];

    // Collect all points to compute bounds
    const allPoints = [];
    segments.forEach(seg => seg.forEach(pt => allPoints.push(pt)));
    if (telemetry?.abs_x != null) allPoints.push({ x: telemetry.abs_x, y: telemetry.abs_y });

    if (allPoints.length === 0) {
      // Draw origin cross only
      const cx = W / 2, cy = H / 2;
      ctx.strokeStyle = C.border;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(cx - 15, cy); ctx.lineTo(cx + 15, cy); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx, cy - 15); ctx.lineTo(cx, cy + 15); ctx.stroke();

      ctx.fillStyle = C.dimText;
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('AWAITING PATH DATA', cx, cy + 40);
      return;
    }

    // Compute scale to fit all points with margin
    const PAD = 40;
    const xs = allPoints.map(p => p.x);
    const ys = allPoints.map(p => p.y);
    const minX = Math.min(...xs, 0) - 10;
    const maxX = Math.max(...xs, 0) + 10;
    const minY = Math.min(...ys, 0) - 10;
    const maxY = Math.max(...ys, 0) + 10;

    const rangeX = maxX - minX || 100;
    const rangeY = maxY - minY || 100;
    const scaleX = (W - PAD * 2) / rangeX;
    const scaleY = (H - PAD * 2) / rangeY;
    const scale  = Math.min(scaleX, scaleY);
    const offX   = PAD + (W - PAD * 2 - rangeX * scale) / 2 - minX * scale;
    const offY   = PAD + (H - PAD * 2 - rangeY * scale) / 2 - minY * scale;

    const toScreen = (x, y) => [offX + x * scale, H - (offY + y * scale)];

    // Draw origin
    const [ox, oy] = toScreen(0, 0);
    ctx.strokeStyle = C.border;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(ox - 10, oy); ctx.lineTo(ox + 10, oy); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ox, oy - 10); ctx.lineTo(ox, oy + 10); ctx.stroke();

    // Obstacles
    obstacles.forEach(obs => {
      const [sx, sy] = toScreen(obs.x, obs.y);
      ctx.fillStyle = C.red;
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(sx, sy, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    });

    // Path segments
    segments.forEach((seg, si) => {
      if (seg.length < 2) return;
      const alpha = 0.3 + 0.7 * (si / Math.max(1, segments.length - 1));
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = C.accent;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      seg.forEach((pt, i) => {
        const [sx, sy] = toScreen(pt.x, pt.y);
        i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy);
      });
      ctx.stroke();
      ctx.globalAlpha = 1;
    });

    // Victims
    victims.forEach(v => {
      const [sx, sy] = toScreen(v.x, v.y);
      // Pulsing marker effect (just draw a star-ish shape)
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
      ctx.font = 'bold 9px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(`V${v.id}`, sx, sy - 12);
    });

    // Current rover position
    if (telemetry?.abs_x != null && telemetry?.abs_y != null) {
      const [rx, ry] = toScreen(telemetry.abs_x, telemetry.abs_y);
      const headingRad = ((telemetry.heading || 0)) * Math.PI / 180;
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
      ctx.lineTo(rx + arrowLen * Math.cos(headingRad), ry - arrowLen * Math.sin(headingRad));
      ctx.stroke();

      // Obstacle ring if active
      if (telemetry.obstacle) {
        ctx.strokeStyle = C.red;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.arc(rx, ry, 20, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Legend
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    [
      [C.green,  '●', 'ROVER'],
      [C.accent, '—', 'PATH'],
      [C.red,    '●', 'OBSTACLE'],
      [C.yellow, '○', 'VICTIM'],
    ].forEach(([color, sym, label], i) => {
      ctx.fillStyle = color;
      ctx.fillText(`${sym} ${label}`, 10, H - 12 - i * 16);
    });

  }, [pathData, telemetry]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => {
      canvas.width  = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
      draw();
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [draw]);

  useEffect(() => { draw(); }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: '100%', height: '100%', display: 'block' }}
    />
  );
}

// ─── Control pad ─────────────────────────────────────────────────────────────

function ControlPad({ sendCommand, status, supportsAuto }) {
  const btns = [
    { cmd: 'F', label: '▲', title: 'Forward',  row: 1, col: 2 },
    { cmd: 'L', label: '◄', title: 'Left',     row: 2, col: 1 },
    { cmd: 'S', label: '■', title: 'Stop',     row: 2, col: 2 },
    { cmd: 'R', label: '►', title: 'Right',    row: 2, col: 3 },
    { cmd: 'B', label: '▼', title: 'Backward', row: 3, col: 2 },
  ];

  const btnStyle = (cmd) => ({
    gridRow: btns.find(b => b.cmd === cmd)?.row,
    gridColumn: btns.find(b => b.cmd === cmd)?.col,
    padding: '10px 0',
    background: cmd === 'S' ? C.accentDim : C.surface,
    border: `1px solid ${cmd === 'S' ? C.accent : C.border}`,
    borderRadius: 6,
    color: cmd === 'S' ? C.accent : C.text,
    fontSize: 18,
    cursor: 'pointer',
    transition: 'background 0.1s, transform 0.1s',
    fontFamily: 'inherit',
    letterSpacing: 0,
  });

  const [pressed, setPressed] = useState(null);

  const handleKey = useCallback((e) => {
    const map = { ArrowUp: 'F', ArrowDown: 'B', ArrowLeft: 'L', ArrowRight: 'R', ' ': 'S' };
    if (map[e.key]) { e.preventDefault(); sendCommand(map[e.key]); }
  }, [sendCommand]);

  useEffect(() => {
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [handleKey]);

  return (
    <div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr 1fr',
        gridTemplateRows: '1fr 1fr 1fr',
        gap: 4,
        maxWidth: 180,
        margin: '0 auto',
      }}>
        {btns.map(({ cmd, label, title }) => (
          <button
            key={cmd}
            title={title}
            style={{
              ...btnStyle(cmd),
              gridRow: btns.find(b => b.cmd === cmd)?.row,
              gridColumn: btns.find(b => b.cmd === cmd)?.col,
              transform: pressed === cmd ? 'scale(0.93)' : 'scale(1)',
            }}
            onMouseDown={() => { setPressed(cmd); sendCommand(cmd); }}
            onMouseUp={() => setPressed(null)}
            onMouseLeave={() => setPressed(null)}
          >
            {label}
          </button>
        ))}
      </div>
      {supportsAuto && (
        <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
          <button
            onClick={() => sendCommand('A')}
            style={{
              flex: 1,
              padding: '6px 0',
              background: status.auto_mode ? C.accentDim : C.surface,
              border: `1px solid ${status.auto_mode ? C.accent : C.border}`,
              borderRadius: 6,
              color: status.auto_mode ? C.accent : C.dimText,
              fontSize: 11,
              cursor: 'pointer',
              fontFamily: 'inherit',
              letterSpacing: 1,
              fontWeight: 600,
            }}
          >
            AUTO {status.auto_mode ? 'ON' : 'OFF'}
          </button>
        </div>
      )}
      <div style={{ marginTop: 6, fontSize: 10, color: C.dimText, textAlign: 'center' }}>
        Arrow keys + Space
      </div>
    </div>
  );
}

// ─── Telemetry chart ─────────────────────────────────────────────────────────

function TelemetryChart({ history }) {
  const data = useMemo(() =>
    history.slice(-60).map(t => ({
      t:       ((t.ms || 0) / 1000).toFixed(1),
      dist:    t.dist === 999 ? null : t.dist,
      accelY:  t.accelY,
      gyroZ:   t.gyroZ,
      estV:    t.estV,
    })), [history]
  );

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', height: '100%', gap: 1, background: C.border }}>
      {[
        { key: 'dist',   label: 'SONAR (cm)', color: C.blue,   domain: [0, 200] },
        { key: 'estV',   label: 'BATT (V)',   color: C.green,  domain: [10, 12.5] },
        { key: 'accelY', label: 'ACCEL Y',    color: C.accent, domain: [-5, 5] },
        { key: 'gyroZ',  label: 'GYRO Z',     color: C.yellow, domain: [-50, 50] },
      ].map(({ key, label, color, domain }) => (
        <div key={key} style={{ background: C.panel, padding: '4px 8px' }}>
          <div style={{ fontSize: 9, color: C.dimText, letterSpacing: 1, marginBottom: 2 }}>{label}</div>
          <ResponsiveContainer width="100%" height={70}>
            <AreaChart data={data} margin={{ top: 0, bottom: 0, left: 0, right: 0 }}>
              <defs>
                <linearGradient id={`grad_${key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={color} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={color} stopOpacity={0}   />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
              <YAxis domain={domain} hide />
              <Tooltip
                contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, fontSize: 10 }}
                labelStyle={{ color: C.dimText }}
                itemStyle={{ color }}
              />
              <Area
                type="monotone" dataKey={key} stroke={color} fill={`url(#grad_${key})`}
                strokeWidth={1.5} dot={false} connectNulls={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ))}
    </div>
  );
}

// ─── Alerts panel ─────────────────────────────────────────────────────────────

function AlertsPanel({ alerts }) {
  return (
    <div style={{ ...styles.panel, gridColumn: '3 / 4', gridRow: '1 / 3' }}>
      <div style={styles.panelHeader}>
        ALERTS
        <span style={{ float: 'right', color: C.red }}>{alerts.filter(a => a.level === 'critical').length} CRIT</span>
      </div>
      <div style={{ ...styles.panelBody, padding: '8px' }}>
        {alerts.length === 0 && (
          <div style={{ color: C.dimText, fontSize: 11, textAlign: 'center', marginTop: 20 }}>No alerts</div>
        )}
        {alerts.map(a => (
          <div key={a.id} style={{
            padding: '6px 8px',
            marginBottom: 4,
            borderRadius: 4,
            borderLeft: `3px solid ${a.level === 'critical' ? C.red : a.level === 'warning' ? C.yellow : C.blue}`,
            background: C.surface,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
              <AlertBadge level={a.level} />
              <span style={{ fontSize: 9, color: C.dimText }}>
                {new Date(a.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <div style={{ fontSize: 11, color: C.text, marginTop: 2, lineHeight: 1.4 }}>
              {a.message}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main app ─────────────────────────────────────────────────────────────────

function App() {
  const { connected, telemetry, pathData, alerts, status, sendCommand } = useRoverWebSocket();
  const [telHistory, setTelHistory] = useState([]);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(null);
  const supportsAuto = Boolean(status?.capabilities?.commands?.includes('A'));

  // Track telemetry history for charts
  useEffect(() => {
    if (!telemetry) return;
    if (!startRef.current) startRef.current = Date.now();
    setTelHistory(prev => [...prev.slice(-200), telemetry]);
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

  const fmtTime = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

  return (
    <div style={styles.app}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <div style={styles.logo}>
          <span style={{ fontSize: 22 }}>⬡</span>
          RESCUE ROVER
          <span style={{ color: C.dimText, fontWeight: 400, fontSize: 12 }}>MISSION CONTROL</span>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginLeft: 12 }}>
          <Pill color={connected ? C.green : C.red} bg={connected ? '#0e2e10' : '#300'}>
            {connected ? '● WS' : '○ DISC'}
          </Pill>
          <Pill color={status.pi_connected ? C.green : C.dimText} bg={C.surface}>
            PI {status.pi_connected ? 'ONLINE' : 'OFFLINE'}
          </Pill>
          {status.obstacle_active && (
            <Pill color={C.red} bg="#300">⚠ OBSTACLE</Pill>
          )}
          {supportsAuto && status.auto_mode && (
            <Pill color={C.accent} bg={C.accentDim}>AUTO</Pill>
          )}
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 20, fontSize: 12 }}>
          <span>
            <span style={{ color: C.dimText }}>MISSION </span>
            <span style={{ color: C.green, fontWeight: 700 }}>{fmtTime(elapsed)}</span>
          </span>
          <span>
            <span style={{ color: C.dimText }}>VICTIMS </span>
            <span style={{ color: C.yellow, fontWeight: 700 }}>{status.victim_count}</span>
          </span>
          <span>
            <span style={{ color: C.dimText }}>DIST </span>
            <span style={{ color: C.text, fontWeight: 700 }}>
              {((pathData?.total_dist_cm || telemetry?.distTotal || 0) / 100).toFixed(1)} m
            </span>
          </span>
          <span>
            <span style={{ color: C.dimText }}>STATE </span>
            <StateBadge state={telemetry?.state} />
          </span>
          <span>
            <span style={{ color: C.dimText }}>BATT </span>
            <span style={{
              fontWeight: 700,
              color: (telemetry?.estV || 12) < 10.8 ? C.red :
                     (telemetry?.estV || 12) < 11.2 ? C.yellow : C.green,
            }}>
              {telemetry?.estV?.toFixed(1) ?? '—'}V
            </span>
          </span>
        </div>
      </div>

      {/* Main grid */}
      <div style={styles.grid}>
        {/* Left panel: Telemetry + Controls */}
        <div style={{ ...styles.panel, gridColumn: '1', gridRow: '1 / 3', borderRight: `1px solid ${C.border}` }}>
          <div style={styles.panelHeader}>TELEMETRY</div>
          <div style={{ ...styles.panelBody, fontSize: 12 }}>
            <TelRow label="X Position"     value={telemetry?.abs_x?.toFixed(1) ?? telemetry?.x?.toFixed(1)}  unit="cm" />
            <TelRow label="Y Position"     value={telemetry?.abs_y?.toFixed(1) ?? telemetry?.y?.toFixed(1)}  unit="cm" />
            <TelRow label="Heading"        value={telemetry?.heading?.toFixed(1)} unit="°" />
            <TelRow label="Sonar"          value={telemetry?.dist === 999 ? 'OOR' : telemetry?.dist}          unit="cm"
              color={telemetry?.dist < 30 ? C.red : C.text}
            />
            <TelRow label="Lap Dist"       value={telemetry?.distLap?.toFixed(1)}   unit="cm" />
            <TelRow label="Total Dist"     value={telemetry?.distTotal?.toFixed(1)} unit="cm" />
            <TelRow label="Est Battery"    value={telemetry?.estV?.toFixed(1)}       unit="V"
              color={(telemetry?.estV ?? 12) < 10.8 ? C.red : (telemetry?.estV ?? 12) < 11.2 ? C.yellow : C.green}
            />
            <TelRow label="RPM"            value={telemetry?.rpm?.toFixed(1)} />
            <TelRow label="AccelY"         value={telemetry?.accelY?.toFixed(2)} unit="m/s²" />
            <TelRow label="GyroZ"          value={telemetry?.gyroZ?.toFixed(2)}  unit="°/s" />
            <TelRow label="Chip Temp"      value={telemetry?.chipTemp?.toFixed(1)} unit="°C" />
            <TelRow label="Flags"          value={telemetry?.flags}
              color={telemetry?.flags === 'OK' ? C.green : C.red}
            />
            <TelRow label="Seq #"          value={telemetry?.seq} />
            <TelRow label="Uptime"         value={telemetry?.ms ? (telemetry.ms / 1000).toFixed(0) : '—'} unit="s" />
            <TelRow label="Obstacles"      value={pathData?.obstacles?.length ?? 0} />
            <TelRow label="Victims"        value={status.victim_count}
              color={status.victim_count > 0 ? C.yellow : C.text}
            />

            <div style={{ marginTop: 16 }}>
              <div style={{ ...styles.panelHeader, padding: '6px 0', marginBottom: 10 }}>CONTROLS</div>
              <ControlPad sendCommand={sendCommand} status={status} supportsAuto={supportsAuto} />
            </div>
          </div>
        </div>

        {/* Center: Path visualization */}
        <div style={{ ...styles.panel, gridColumn: '2', gridRow: '1' }}>
          <div style={styles.panelHeader}>
            PATH VISUALIZATION
            <span style={{ float: 'right', color: C.dimText, fontWeight: 400 }}>
              {pathData?.segments?.length ?? 0} seg · {pathData?.obstacles?.length ?? 0} obs
            </span>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <PathCanvas pathData={pathData} telemetry={telemetry} />
          </div>
        </div>

        {/* Bottom: Charts */}
        <div style={{ ...styles.panel, gridColumn: '2', gridRow: '2' }}>
          <div style={styles.panelHeader}>SENSOR GRAPHS — LAST 60 PACKETS</div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <TelemetryChart history={telHistory} />
          </div>
        </div>

        {/* Right: Alerts */}
        <AlertsPanel alerts={alerts} />
      </div>
    </div>
  );
}

export default App;
