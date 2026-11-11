"use strict";

const ELK = require("elkjs/lib/elk.bundled.js");

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  input += chunk;
});
process.stdin.on("end", async () => {
  try {
    const request = JSON.parse(input);
    const elk = new ELK();
    const result = Array.isArray(request.graphs)
      ? { graphs: await Promise.all(request.graphs.map((graph) => elk.layout(graph))) }
      : await elk.layout(request);
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    const message = error instanceof Error ? error.stack || error.message : String(error);
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
  }
});
