// Leak check: the built client must contain nothing derived from the sealed answer key.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
const BANNED = [/answer_key/i, /true_series/i, /is_decoy/i, /offender_id/i, /sealed_db/i];
const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
const hits = walk("dist").flatMap((f) => BANNED.filter((r) => r.test(readFileSync(f, "utf8"))).map((r) => `${f}: ${r}`));
if (hits.length) { console.error("LEAK:\n" + hits.join("\n")); process.exit(1); }
console.log(`leak check: ${walk("dist").length} built files, no answer-key terms`);
