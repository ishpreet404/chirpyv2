import React from "react";

export default function CameraFeed({ streamUrl }) {
  return (
    <div className="panel camera-panel">
      <div className="panel-title">Camera Feed</div>
      <div className="camera-frame">
        <div className="camera-feed">
          <img src={streamUrl} alt="mjpeg stream" />
        </div>
      </div>
    </div>
  );
}
