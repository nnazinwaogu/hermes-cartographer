import { Router } from "./app.js";

const router = new Router();

export function boot(port) {
  return startServer(port);
}
