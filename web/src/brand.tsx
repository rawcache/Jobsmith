import { useEffect, useState } from "react";

/* The brand: a pixel anvil for the mark, and smith (an anvil and hammer) drawn in ASCII. */

const MARK = ["...........##...", "..........##....", ".........##.....", "...####.##......", "...######.......", "...####.........", "################", ".###############", "..##############", "......########..", ".......######...", "......########..", "....############"];

/** The mark: an anvil and hammer on a pixel grid. */
export function PixelMark({ size = 22, className = "" }: { size?: number; className?: string }) {
  return (
    <svg className={`pixmark ${className}`} width={size} height={size * 13 / 16} viewBox="0 0 64 52" fill="currentColor" aria-hidden="true">
      {MARK.flatMap((row, y) => [...row].map((c, x) => c === "#" ? <rect key={`${x}-${y}`} x={x * 4} y={y * 4} width="3" height="3" /> : null))}
    </svg>
  );
}

export const SMITH = "                                                   ,t|\n                                                  ii,\n                                                .z|\n                       ;                       iz,\n                .                            .i!\n                                            !t,\n                                          .ci\n                       :. i             .ic|\n                           .     ,UUdU9dzoA99AA.\n                           .     :$B8$$BO8$8BOB.\n                                 :BOOB8O$$B8OOO,\n.::,.....,,.,,,.,.;::,;;,:;:;,:;;;,;;,;;;,;,;;,,,,:;:;::,:::,:.\n   .,,;!tojzzoojzoj9dAdAdAUUd99U9A99A9999UUA99UAUA99AAUdU9d9U9;\n           .,:;:,:;;cjA8BOOOB$B$$O8$OOB8$$$$88OOOB$OBB8$$O8dVc.\n                              c$8B$BO$OB$BO8$8B$O$8Bo\n                               i$OOO$8$B8O$BB$BB8$BV\n                                zBB$OOBB$$OBB$BO$8V\n                                .U8OOOOO$BBOO8$889.\n                       ,$$$BB@@@$@88@B88@$$88$$$$B$BB8B$BBB|\n                      c8B@$88@B$@$B$8$$B@8B$$@B@@$@@B$8BB88@o\n                     tjjzzVoVVVoVVVjVjVVzzzjzVzzVjzzVVzojjojoj";

/** smith, in ASCII. Draws itself in once, row by row (instantly if you prefer less motion). */
export function AsciiSmith({ className = "", reveal = true }: { className?: string; reveal?: boolean }) {
  const lines = SMITH.split("\n");
  const still = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(reveal && !still ? 0 : lines.length);
  useEffect(() => {
    if (shown >= lines.length) return;
    const t = setTimeout(() => setShown(n => n + 1), 45);
    return () => clearTimeout(t);
  }, [shown]);
  return (
    <pre className={`ascii-smith ${className}`} role="img" aria-label="smith: an anvil and hammer drawn in ASCII">
      {lines.map((l, i) => <span key={i} style={{ opacity: i < shown ? 1 : 0 }}>{l + "\n"}</span>)}
    </pre>
  );
}
