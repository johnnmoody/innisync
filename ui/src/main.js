import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";

import { st, audio } from "./lib/store.svelte.js";

mount(App, { target: document.getElementById("app") });
// read by the app's --selftest (run.py) and handy when debugging in the web inspector
window.__innisync = { st, audio };
