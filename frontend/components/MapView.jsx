import React, { useMemo } from "react";

const baseWidth = 1000;
const baseHeight = 600;
const cellSizeM = 1.0;

export default function MapView({ path, victims, robot }) {
  const { polyline, robotPoint, robotHeading, victimPoints, zones } = useMemo(() => {
    const points = Array.isArray(path) && path.length > 0 ? path : [{ x: 0, y: 0 }];
    const allPoints = [...points];

    if (robot) allPoints.push({ x: robot.x || 0, y: robot.y || 0 });
    if (Array.isArray(victims)) {
      victims.forEach((v) => allPoints.push({ x: v.x || 0, y: v.y || 0 }));
    }

    let minX = allPoints[0].x;
    let maxX = allPoints[0].x;
    let minY = allPoints[0].y;
    let maxY = allPoints[0].y;

    allPoints.forEach((p) => {
      minX = Math.min(minX, p.x);
      maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y);
      maxY = Math.max(maxY, p.y);
    });

    const pad = 2;
    const rangeX = Math.max(maxX - minX, 1);
    const rangeY = Math.max(maxY - minY, 1);
    const scale = Math.min(baseWidth / (rangeX + pad), baseHeight / (rangeY + pad));

    const mapPoint = (p) => ({
      x: (p.x - minX + pad / 2) * scale,
      y: (maxY - p.y + pad / 2) * scale
    });

    const polylinePoints = points.map((p) => {
      const m = mapPoint(p);
      return `${m.x.toFixed(1)},${m.y.toFixed(1)}`;
    });

    const robotP = mapPoint({ x: robot?.x || 0, y: robot?.y || 0 });

    const victimPts = (victims || []).map((v) => mapPoint({ x: v.x || 0, y: v.y || 0 }));

    const cellSet = new Set();
    points.forEach((p) => {
      const cx = Math.floor(p.x / cellSizeM);
      const cy = Math.floor(p.y / cellSizeM);
      cellSet.add(`${cx},${cy}`);
    });

    const zoneRects = Array.from(cellSet).map((key) => {
      const [cx, cy] = key.split(",").map(Number);
      const zx = cx * cellSizeM;
      const zy = cy * cellSizeM;
      const topLeft = mapPoint({ x: zx, y: zy + cellSizeM });
      const bottomRight = mapPoint({ x: zx + cellSizeM, y: zy });
      return {
        x: topLeft.x,
        y: topLeft.y,
        w: Math.max(bottomRight.x - topLeft.x, 2),
        h: Math.max(bottomRight.y - topLeft.y, 2)
      };
    });

    return {
      polyline: polylinePoints.join(" "),
      robotPoint: robotP,
      robotHeading: robot?.heading || 0,
      victimPoints: victimPts,
      zones: zoneRects
    };
  }, [path, victims, robot]);

  return (
    <div className="panel map-panel">
      <div className="panel-title">Exploration Map</div>
      <svg className="map-svg" viewBox={`0 0 ${baseWidth} ${baseHeight}`}>
        {zones.map((z, idx) => (
          <rect
            key={`zone-${idx}`}
            className="map-zone"
            x={z.x}
            y={z.y}
            width={z.w}
            height={z.h}
          />
        ))}
        <polyline className="map-path" points={polyline} />
        {victimPoints.map((v, idx) => (
          <circle key={`victim-${idx}`} className="map-victim" cx={v.x} cy={v.y} r={6} />
        ))}
        <g transform={`translate(${robotPoint.x},${robotPoint.y}) rotate(${-robotHeading})`}>
          <polygon className="map-robot" points="12,0 -10,-8 -10,8" />
        </g>
      </svg>
    </div>
  );
}
