/**
 * Bind the screen's identify interaction to the map event stream.
 *
 * Keeping this small controller independent of Leaflet's DOM implementation
 * makes the event contract testable with the same `on`/`off`/`fire` interface
 * used by Leaflet maps, while the production caller passes the real map.
 */
export const bindMapIdentify = (map, resolveHandler, fallbackHandler) => {
  const onClick = (event) => {
    const handler = resolveHandler();
    if (handler) handler(event);
    else fallbackHandler(event);
  };
  map.on("click", onClick);
  return () => map.off("click", onClick);
};

export const updateIdentifyTarget = (target, result) => {
  if (!target) return;
  target.textContent = result.message;
  target.dataset.identifyState = result.status;
  target.className = `map-identify-panel map-identify map-identify-${result.status}`;
};
