import Tooltip from "@mui/material/Tooltip";
import { q } from "./locale";
export function Help({ text }) {
  return <Tooltip title={q(text)} arrow enterTouchDelay={0}><button type="button" className="queue-help" aria-label={q(text)}><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M7.7 7a2.4 2.4 0 0 1 4.6.9c0 1.7-2.3 1.7-2.3 3.3M10 14.3h.01" /></svg></button></Tooltip>;
}
