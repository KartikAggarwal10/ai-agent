// Thin entry point for the existing seepost.js Playwright script.
// seepost.js itself is untouched - it only exports GET({email, password, post_id}).
// Usage: node run_seepost.mjs <email> <password> <post_id>
import { GET } from "./seepost.js";

const [, , email, password, post_id] = process.argv;

if (!email || !password || !post_id) {
    console.error("usage: node run_seepost.mjs <email> <password> <post_id>");
    process.exit(1);
}

await GET({ email, password, post_id });
