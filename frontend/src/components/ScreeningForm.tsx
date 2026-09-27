import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

import type { AoiGeometry } from "../api";
import { EXAMPLE_AOI, parseAoi } from "../geojson";

interface Props {
  aoi: AoiGeometry | null;
  drawing: boolean;
  submitting: boolean;
  error: string | null;
  onAoi: (aoi: AoiGeometry | null) => void;
  onDrawingChange: (drawing: boolean) => void;
  onSubmit: (name: string, aoi: AoiGeometry) => void;
}

export function ScreeningForm({
  aoi,
  drawing,
  submitting,
  error,
  onAoi,
  onDrawingChange,
  onSubmit,
}: Props) {
  const [name, setName] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      onAoi(parseAoi(await file.text()));
      setUploadError(null);
      onDrawingChange(false);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (aoi && name.trim()) onSubmit(name.trim(), aoi);
  }

  const vertexCount = aoi
    ? (aoi.type === "Polygon" ? [aoi.coordinates] : aoi.coordinates).flat(2).length
    : 0;

  return (
    <form className="panel-section" onSubmit={handleSubmit} aria-label="New screening">
      <h2>New screening</h2>
      <label className="field">
        <span>Project name</span>
        <input
          value={name}
          maxLength={200}
          placeholder="e.g. North Ridge Solar"
          onChange={(e) => setName(e.target.value)}
        />
      </label>

      <div className="field">
        <span>Project area (AOI)</span>
        <div className="button-row">
          <button
            type="button"
            className={drawing ? "button button--active" : "button"}
            onClick={() => onDrawingChange(!drawing)}
          >
            {drawing ? "Cancel drawing" : "Draw on map"}
          </button>
          <button type="button" className="button" onClick={() => fileInput.current?.click()}>
            Upload GeoJSON
          </button>
          <button
            type="button"
            className="button button--link"
            onClick={() => {
              onAoi(EXAMPLE_AOI);
              onDrawingChange(false);
              if (!name) setName("Poudre River example");
            }}
          >
            Use example
          </button>
        </div>
        <input
          ref={fileInput}
          type="file"
          accept=".geojson,.json,application/geo+json,application/json"
          hidden
          data-testid="aoi-file"
          onChange={handleFile}
        />
        {drawing && (
          <p className="hint">Click to add vertices; click the first vertex to finish.</p>
        )}
        {aoi && !drawing && (
          <p className="hint">
            AOI defined ({vertexCount} vertices).{" "}
            <button type="button" className="button--link" onClick={() => onAoi(null)}>
              Clear
            </button>
          </p>
        )}
        {!aoi && !drawing && (
          <p className="hint">Within Colorado, up to 250 km².</p>
        )}
      </div>

      {(uploadError || error) && (
        <p className="error" role="alert">
          {uploadError ?? error}
        </p>
      )}

      <button
        type="submit"
        className="button button--primary"
        disabled={!aoi || !name.trim() || submitting}
      >
        {submitting ? "Submitting…" : "Run screening"}
      </button>
    </form>
  );
}
