export interface GeoGebraCommandAPI {
  evalCommand: (command: string) => boolean
  setColor?: (object: string, red: number, green: number, blue: number) => void
  setLineThickness?: (object: string, thickness: number) => void
  exists?: (object: string) => boolean
}

/** Styling commands have no algebra result; apply their documented API form. */
export function runGeoGebraCommand(api: GeoGebraCommandAPI, command: string): boolean {
  const thickness = command.match(/^SetLineThickness\(\s*([^,()]+)\s*,\s*(-?\d+)\s*\)$/i)
  if (thickness && api.setLineThickness) {
    const value = Number(thickness[2])
    const object = thickness[1].trim()
    if (value === -1 || (value >= 1 && value <= 13)) {
      if (api.exists && !api.exists(object)) return false
      api.setLineThickness(object, value)
      return true
    }
  }
  const color = command.match(
    /^SetColou?r\(\s*([^,()]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/i
  )
  if (color && api.setColor) {
    const rgb = color.slice(2).map(Number)
    const object = color[1].trim()
    if (rgb.every(value => Number.isFinite(value) && value >= 0 && value <= 1)) {
      if (api.exists && !api.exists(object)) return false
      api.setColor(
        object,
        Math.round(rgb[0] * 255),
        Math.round(rgb[1] * 255),
        Math.round(rgb[2] * 255)
      )
      return true
    }
  }
  return api.evalCommand(command)
}
