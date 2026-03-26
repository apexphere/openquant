// pyright-bridge.ts
import { spawn as spawn2 } from "child_process";
import { WebSocketServer } from "ws";
import { toSocket, WebSocketMessageReader, WebSocketMessageWriter } from "vscode-ws-jsonrpc";
import { StreamMessageReader, StreamMessageWriter } from "vscode-jsonrpc/node.js";
import { readFileSync as readFileSync2, writeFileSync as writeFileSync2, existsSync as existsSync2 } from "fs";
import path2, { dirname, join } from "path";
import { fileURLToPath as fileURLToPath2, pathToFileURL } from "url";
import "dotenv/config";

// formatting.ts
import { spawn } from "child_process";
import { readFileSync, writeFileSync, existsSync, mkdtempSync, unlinkSync } from "fs";
import path from "path";
import { tmpdir } from "os";
import { fileURLToPath } from "url";
async function handleFormatting(msg, writer, wsWriter, ruffPath) {
  try {
    console.log("\u{1F3A8} Formatting request intercepted, handling with ruff...");
    const textDocument = msg.params?.textDocument;
    const uri = textDocument?.uri;
    if (!uri) {
      console.error("\u274C No URI in formatting request");
      wsWriter.write({
        jsonrpc: "2.0",
        id: msg.id,
        error: {
          code: -32602,
          message: "Invalid params: missing textDocument.uri"
        }
      });
      return;
    }
    console.log(`\u{1F4E5} Received URI: ${uri}`);
    let filePath;
    try {
      filePath = fileURLToPath(uri);
      console.log(`\u{1F50D} File path: ${filePath}`);
    } catch (err) {
      console.error(`\u274C Failed to convert URI to path:`, err);
      wsWriter.write({
        jsonrpc: "2.0",
        id: msg.id,
        error: {
          code: -32602,
          message: "Invalid file URI"
        }
      });
      return;
    }
    if (!existsSync(ruffPath)) {
      console.error("\u274C Ruff binary not found at:", ruffPath);
      wsWriter.write({
        jsonrpc: "2.0",
        id: msg.id,
        error: {
          code: -32e3,
          message: "Ruff binary not available"
        }
      });
      return;
    }
    const isRangeFormatting = msg.method === "textDocument/rangeFormatting";
    const isFullFormatting = msg.method === "textDocument/formatting";
    if (isRangeFormatting) {
      console.log("\u{1F4DD} Range formatting not fully implemented yet, falling back to full document formatting");
    }
    if (!isFullFormatting && !isRangeFormatting) {
      console.log("\u26A0\uFE0F Unsupported formatting method:", msg.method);
      writer.write(msg);
      return;
    }
    const tempDir = mkdtempSync(path.join(tmpdir(), "ruff-format-"));
    const tempFile = path.join(tempDir, "temp.py");
    try {
      let fileContent;
      if (existsSync(filePath)) {
        fileContent = readFileSync(filePath, "utf-8");
        console.log(`\u{1F4D6} Read file from disk: ${filePath}`);
        console.log(`   Content length: ${fileContent.length} chars`);
      } else {
        fileContent = msg.params?.textDocument?.text || "";
        console.log(`\u26A0\uFE0F File not found on disk, using params or empty content`);
      }
      writeFileSync(tempFile, fileContent);
      console.log(`\u{1F4BE} Wrote content to temp file: ${tempFile}`);
      const ruff = spawn(ruffPath, ["format", tempFile], {
        cwd: tempDir,
        stdio: ["pipe", "pipe", "pipe"]
      });
      let stdout = "";
      let stderr = "";
      ruff.stdout.on("data", (data) => {
        stdout += data.toString();
      });
      ruff.stderr.on("data", (data) => {
        stderr += data.toString();
      });
      await new Promise((resolve, reject) => {
        ruff.on("close", (code) => {
          console.log(`\u{1F527} Ruff process exited with code: ${code}`);
          if (stderr)
            console.log(`   stderr: ${stderr}`);
          if (stdout)
            console.log(`   stdout: ${stdout}`);
          if (code === 0) {
            resolve(void 0);
          } else {
            reject(new Error(`Ruff exited with code ${code}: ${stderr}`));
          }
        });
        ruff.on("error", reject);
      });
      const formattedContent = readFileSync(tempFile, "utf-8");
      const lines = fileContent.split("\n");
      const lineCount = lines.length;
      const hasTrailingNewline = lines[lineCount - 1] === "";
      let endLine;
      let endCharacter;
      if (hasTrailingNewline && lineCount >= 2) {
        endLine = lineCount - 2;
        endCharacter = lines[lineCount - 2].length;
      } else {
        endLine = lineCount - 1;
        endCharacter = lines[lineCount - 1].length;
      }
      const edits = [{
        range: {
          start: { line: 0, character: 0 },
          end: { line: endLine, character: endCharacter }
        },
        newText: formattedContent
      }];
      console.log("\u2705 Formatting completed successfully");
      console.log(`\u{1F4E4} Sending response with ${edits.length} edit(s)`);
      console.log(`   Range: (${edits[0].range.start.line},${edits[0].range.start.character}) -> (${edits[0].range.end.line},${edits[0].range.end.character})`);
      console.log(`   New text length: ${formattedContent.length} chars`);
      console.log(`   First 100 chars: ${formattedContent.substring(0, 100)}`);
      const response = {
        jsonrpc: "2.0",
        id: msg.id,
        result: edits
      };
      console.log("\u{1F4E8} Response object:", JSON.stringify(response).substring(0, 500));
      wsWriter.write(response);
    } finally {
      try {
        if (existsSync(tempFile))
          unlinkSync(tempFile);
      } catch (err) {
        console.warn("\u26A0\uFE0F Failed to clean up temp file:", err);
      }
    }
  } catch (error) {
    console.error("\u274C Formatting error:", error);
    wsWriter.write({
      jsonrpc: "2.0",
      id: msg.id,
      error: {
        code: -32e3,
        message: `Formatting failed: ${error.message}`
      }
    });
  }
}

// pyright-bridge.ts
var __filename = fileURLToPath2(import.meta.url);
var __dirname = dirname(__filename);
function parseArgs() {
  const args2 = process.argv.slice(2);
  const parsed = {};
  for (let i = 0; i < args2.length; i++) {
    if (args2[i].startsWith("--")) {
      const key = args2[i].slice(2);
      const value = args2[i + 1];
      if (value && !value.startsWith("--")) {
        parsed[key] = value;
        i++;
      }
    }
  }
  return parsed;
}
var args = parseArgs();
var PYRIGHT_WS_PORT = Number(args["port"]);
var BOT_ROOT = args["bot-root"];
var JESSE_ROOT = args["jesse-root"];
var PYRIGHT_PATH = join(__dirname, "node_modules/pyright/dist/pyright-langserver.js");
var RUFF_PATH = process.env.RUFF_PATH || join(__dirname, "bin/ruff");
function deployPyrightConfig() {
  const templatePath = join(__dirname, "pyrightconfig.json");
  const targetPath = join(BOT_ROOT, "pyrightconfig.json");
  if (!existsSync2(templatePath)) {
    console.warn(`Warning: No pyrightconfig.json template found at ${templatePath}`);
    return;
  }
  const normalizedBotRoot = BOT_ROOT.replace(/\\/g, "/");
  const normalizedJesseRoot = (JESSE_ROOT || "").replace(/\\/g, "/");
  let configContent = readFileSync2(templatePath, "utf-8");
  configContent = configContent.replace(/\$\{BOT_ROOT\}/g, normalizedBotRoot);
  configContent = configContent.replace(/\$\{JESSE_ROOT\}/g, normalizedJesseRoot);
  const config = JSON.parse(configContent);
  writeFileSync2(targetPath, JSON.stringify(config, null, 2));
  console.log(`Deployed pyrightconfig.json to ${targetPath}`);
}
function startPyrightBridge() {
  if (!PYRIGHT_WS_PORT || !BOT_ROOT || !JESSE_ROOT) {
    console.error("Error: --port and --bot-root and --jesse-root are required");
    console.error("Usage: npx tsx index.ts --port <PORT> --bot-root <BOT_ROOT> --jesse-root <JESSE_ROOT>");
    process.exit(1);
  }
  deployPyrightConfig();
  const wss = new WebSocketServer({ port: PYRIGHT_WS_PORT, path: "/lsp" });
  console.log(`Pyright WS bridge running on ws://localhost:${PYRIGHT_WS_PORT}/lsp`);
  console.log(`Execution root: ${BOT_ROOT}`);
  console.log(`Ruff path: ${RUFF_PATH}`);
  wss.on("connection", (ws) => {
    console.log("Client connected, spawning Pyright...");
    console.log(`Spawning Pyright with cwd: ${BOT_ROOT}`);
    const pyright = spawn2(process.execPath, [PYRIGHT_PATH, "--stdio"], {
      cwd: BOT_ROOT,
      env: process.env
    });
    console.log("Pyright spawned, setting up message readers/writers...");
    const reader = new StreamMessageReader(pyright.stdout);
    const writer = new StreamMessageWriter(pyright.stdin);
    const socket = toSocket(ws);
    const wsReader = new WebSocketMessageReader(socket);
    const wsWriter = new WebSocketMessageWriter(socket);
    wsReader.listen((msg) => {
      console.log("\u2192 Client to Pyright:", JSON.stringify(msg).substring(0, 200));
      if (msg.method === "initialize") {
        console.log("\u{1F527} Auto-injecting project configuration");
        msg.params = msg.params || {};
        msg.params.rootUri = pathToFileURL(BOT_ROOT).toString();
        msg.params.workspaceFolders = [
          {
            uri: pathToFileURL(BOT_ROOT).toString(),
            name: "jesse-ai"
          }
        ];
        console.log("\u2713 rootUri:", msg.params.rootUri);
      }
      if (msg.params?.textDocument?.uri) {
        const uri = msg.params.textDocument.uri;
        if (uri.startsWith("file://")) {
          try {
            const filePath = fileURLToPath2(uri);
            if (!existsSync2(filePath)) {
              const absolutePath = path2.join(BOT_ROOT, filePath);
              msg.params.textDocument.uri = pathToFileURL(absolutePath).toString();
              console.log(`\u{1F504} Converted relative URI to absolute: ${uri} -> ${msg.params.textDocument.uri}`);
            }
          } catch (err) {
            const absolutePath = path2.join(BOT_ROOT, uri.replace("file:///", "").replace("file://", ""));
            msg.params.textDocument.uri = pathToFileURL(absolutePath).toString();
            console.log(`\u{1F504} Converted relative URI to absolute: ${uri} -> ${msg.params.textDocument.uri}`);
          }
        } else {
          const absolutePath = path2.join(BOT_ROOT, uri);
          msg.params.textDocument.uri = pathToFileURL(absolutePath).toString();
          console.log(`\u{1F504} Converted relative URI to absolute: ${uri} -> ${msg.params.textDocument.uri}`);
        }
      }
      if (msg.method === "textDocument/formatting" || msg.method === "textDocument/rangeFormatting") {
        handleFormatting(msg, writer, wsWriter, RUFF_PATH);
        return;
      }
      writer.write(msg);
    });
    reader.listen((msg) => {
      console.log("\u2190 Pyright to Client:", JSON.stringify(msg).substring(0, 200));
      wsWriter.write(msg);
    });
    ws.on("close", () => {
      console.log("Client disconnected, killing Pyright...");
      pyright.kill();
    });
    pyright.on("error", (err) => {
      console.error("Pyright process error:", err);
      ws.close();
    });
    pyright.stderr.on("data", (data) => {
      console.error("Pyright stderr:", data.toString());
    });
  });
}

// index.ts
startPyrightBridge();
