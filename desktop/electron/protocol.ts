export const SUPPORTED_PROTOCOL_MAJOR = 1;
export const DESKTOP_PROTOCOL_VERSION = "1.0.0";

export type ProtocolCompatibility = {
  compatible: boolean;
  reason?: string;
};

export function checkProtocolCompatibility(
  protocol: string
): ProtocolCompatibility {
  const value = String(protocol ?? "").trim();
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(value);
  if (!match) {
    return {
      compatible: false,
      reason:
        "Unsupported Agent protocol '" +
        value +
        "'. Expected semantic protocol version " +
        DESKTOP_PROTOCOL_VERSION +
        "."
    };
  }

  const major = Number(match[1]);
  if (major !== SUPPORTED_PROTOCOL_MAJOR) {
    return {
      compatible: false,
      reason:
        "Unsupported Agent protocol " +
        value +
        ". Desktop supports protocol major " +
        SUPPORTED_PROTOCOL_MAJOR +
        "."
    };
  }

  return { compatible: true };
}
