/** Optional real Chromium check. Requires an explicit browser executable; no profile reuse. */
import {
  spawn
} from 'node:child_process';
import {
  mkdtemp,
  readFile,
  writeFile,
  mkdir
} from 'node:fs/promises';
import {
  tmpdir
} from 'node:os';
import {
  join,
  extname,
  resolve,
  relative,
  isAbsolute
} from 'node:path';
import {
  fileURLToPath
} from 'node:url';
import {
  createServer
} from 'node:http';
const executable = process.argv[2] ?? process.env.PAPERFACT_TEST_BROWSER;
if(! executable) throw new Error('Pass an explicit Chromium/Edge executable path.');
const root = fileURLToPath(new URL('.', import.meta.url)), profile = await mkdtemp(join(tmpdir(), 'paperfact-mobile-fixture-'));
const server = createServer(async(request, response) => {
  const name = decodeURIComponent(new URL(request.url, 'http://localhost').pathname),
  path = resolve(root, '.' +(name === '/' ? '/index.html': name));
  const local = relative(root, path);
  if(local.startsWith('..') || isAbsolute(local)) {
    response.writeHead(404);
    response.end();
    return;
  }
  try {
    const bytes = await readFile(path);
    response.writeHead(
    200,
    {
      'Content-Type': ({
        '.mjs': 'text/javascript',
        '.html': 'text/html',
        '.css': 'text/css',
        '.svg': 'image/svg+xml',
        '.webmanifest': 'application/manifest+json'
      })[extname(path)] ?? 'application/octet-stream'
    }
    );
    response.end(bytes);
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = spawn(
executable,
['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
'--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
{
  stdio: ['ignore', 'ignore', 'pipe'],
  windowsHide: true
}
);
let socket;
const pending = new Map();
let nextId = 0, session;
const send =(method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
  const id =++ nextId;
  const timeout = setTimeout(() => {
    pending.delete(id);
    reject(new Error('Browser command timed out: ' + method));
  }, 5000);
  pending.set(
  id,
  {
    resolve: value => {
      clearTimeout(timeout);
      resolve(value);
    },
    reject: error => {
      clearTimeout(timeout);
      reject(error);
    }
  }
  );
  socket.send(JSON.stringify({
    id,
    method,
    params,
    ...(sessionId ? {
      sessionId
    }
    : {})
  }));
});
try {
  const endpoint = await new Promise((resolve, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('Browser did not expose test debugging socket')),
    15000);
    browser.stderr.on(
    'data',
    chunk => {
      output += chunk;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if(match) {
        clearTimeout(timeout);
        resolve(match[1]);
      }
    }
    );
    browser.on('error', reject);
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  socket.onmessage = event => {
    const value = JSON.parse(event.data);
    if(value.id) {
      const promise = pending.get(value.id);
      pending.delete(value.id);
      if(value.error) promise.reject(new Error(value.error.message));
      else promise.resolve(value.result);
    } else if(value.method === 'Runtime.exceptionThrown') process.stderr.write('Browser exception: ' + JSON.stringify(value.params.exceptionDetails) + '\n');
  };
  const target = await send('Target.createTarget', {
    url: 'about:blank'
  }, null);
  session =(await send('Target.attachToTarget', {
    targetId: target.targetId,
    flatten: true
  }, null)).sessionId;
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', {
    url: `http://127.0.0.1:${server.address().port}/browser-test.html`
  });
  let finished = false;
  for(let tick = 0; tick < 160; tick++) {
    await new Promise(resolve => setTimeout(resolve, 250));
    const result = await send(
    'Runtime.evaluate',
    {
      expression: 'JSON.stringify({done:document.body?.dataset.result,text:document.querySelector("#result")?.textContent})',
      returnByValue: true
    }
    );
    const value = JSON.parse(result.result.value ?? '{}');
    if(value.done) {
      console.log(value.text);
      if(value.done !== 'pass') process.exitCode = 1;
      finished = true;
      break;
    }
  }
  if(! finished) {
    const result = await send(
    'Runtime.evaluate',
    {
      expression: 'document.querySelector("#result")?.textContent',
      returnByValue: true
    }
    );
    throw new Error('Browser fixture timed out: ' + result.result.value);
  }
  if(process.argv[3]) {
    await mkdir(process.argv[3], {
      recursive: true
    });
    await send('Page.navigate', {
      url: `http://127.0.0.1:${server.address().port}/index.html`
    });
    for(let tick = 0; tick < 40; tick++) {
      await new Promise(resolve => setTimeout(resolve, 100));
      const ready = await send(
      'Runtime.evaluate',
      {
        expression: 'Boolean(document.querySelector(".layout"))',
        returnByValue: true
      }
      );
      if(ready.result.value) break;
    }
    await send('Runtime.evaluate', {
      expression: 'document.querySelector(".paper-card")?.click()'
    });
    await send('Runtime.evaluate', {expression:'document.querySelector("#tab-slides")?.click()'});
    for(let tick=0;tick<60;tick++) {
      const ready=await send('Runtime.evaluate',{expression:'Boolean(document.querySelector(".slide-surface img")?.complete && document.querySelector(".slide-surface img")?.naturalWidth)',returnByValue:true});
      if(ready.result.value) break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    for(const [name, width, height, mobile] of[['slides-desktop', 1320, 900, false], ['slides-phone', 390, 844, true]]) {
      await send(
      'Emulation.setDeviceMetricsOverride',
      {
        width,
        height,
        deviceScaleFactor: 1,
        mobile
      }
      );
      await new Promise(resolve => setTimeout(resolve, 200));
      const shot = await send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: false
      });
      await writeFile(join(process.argv[3], name + '.png'), Buffer.from(shot.data, 'base64'));
    }
  }
} finally {
  if(socket?.readyState === WebSocket.OPEN) {
    await send('Browser.close', {}, null).catch(() => {});
    socket.close();
  }
  browser.kill();
  server.close();
}
