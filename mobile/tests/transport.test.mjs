import test from 'node:test';
import assert from 'node:assert/strict';
import {
  HttpTransport,
  CHUNK
} from '../transport.mjs';
import {
  cacheable,
  SHELL
} from '../sw-policy.mjs';
import {
  messages
} from '../i18n.mjs';
import {
  readFileSync,
  readdirSync
} from 'node:fs';
import {
  spawnSync
} from 'node:child_process';
const json = value => new Response(JSON.stringify(value), {
  headers: {
    'content-type': 'application/json'
  }
});
test(
'fixed session and blob routes carry token only in header and suppress redirects/cookies',
async() => {
  const seen =[];
  const transport = new HttpTransport(
  'https://example.org',
  {
    fetch: async(url, options) => {
      seen.push([url, options]);
      return url.endsWith('/info') ? json({
        workspace_id: 'work',
        device_id: 'phone'
      }): json({
        data: 'YWJj'
      });
    }
  }
  );
  assert.deepEqual(await transport.session_info('private-token'), {
    workspace_id: 'work',
    device_id: 'phone'
  });
  assert.deepEqual(await transport.blob_read('private-token', 'a'.repeat(64), 3, 0), new Uint8Array([97,
  98, 99]));
  for(const [url, options] of seen) {
    assert.equal(url.includes('private-token'), false);
    assert.equal(options.body.includes('private-token'), false);
    assert.equal(options.headers.Authorization, 'Bearer private-token');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
  }
}
);
test(
'reject credentials, paths, fragments, queries and nonloopback HTTP origins',
() => {
  for(const url of['http://example.org', 'https://u:p@example.org', 'https://example.org/path', 'https://example.org/?token=x',
  'https://example.org/#x']) assert.throws(() => new HttpTransport(url));
  assert.ok(new HttpTransport('http://127.0.0.1:8000'));
}
);
test(
'strict identity and exact base64/range responses reject malformed data',
async() => {
  const response = {
    workspace_id: 'work',
    device_id: 'phone',
    token: 'do-not-store'
  };
  let transport = new HttpTransport('https://example.org', {
    fetch: async() => json(response)
  });
  await assert.rejects(transport.session_info('token'));
  for(const data of['YQ', 'YQ==\n', 'YR==', 'YWI=']) {
    transport = new HttpTransport('https://example.org', {
      fetch: async() => json({
        data
      })
    });
    await assert.rejects(transport.blob_read('token', 'a'.repeat(64), 1, 0));
  }
  await assert.rejects(transport.blob_read('token', 'a'.repeat(64), 1, 0, CHUNK + 1));
}
);
test(
'bounded streamed response and sanitized HTTP/connection errors',
async() => {
  let transport = new HttpTransport(
  'https://example.org',
  {
    fetch: async() => new Response(
    'x'.repeat(2 * 1024 * 1024 + 1),
    {
      headers: {
        'content-type': 'application/json'
      }
    }
    )
  }
  );
  await assert.rejects(transport.session_info('token'), /response_too_large/);
  transport = new HttpTransport(
  'https://example.org',
  {
    fetch: async() => {
      throw new Error('https://private-token@secret-host');
    }
  }
  );
  await assert.rejects(transport.session_info('private-token'), error => error.message === 'connection_failed');
  transport = new HttpTransport(
  'https://example.org',
  {
    fetch: async() => new Response('private failure', {
      status: 403
    })
  }
  );
  await assert.rejects(transport.session_info('private-token'), /session_denied/);
}
);
test(
'service worker caches only exact static shell, never auth or research requests',
() => {
  const scope = 'https://example.org/mobile/';
  assert.equal(cacheable(new Request(scope + 'app.mjs'), scope), true);
  for(const request of[new Request(scope + 'app.mjs?private=1'), new Request(scope + 'private.pdf'), new Request(scope + 'app.mjs',
  {
    headers: {
      Authorization: 'Bearer secret'
    }
  }), new Request('https://other.org/mobile/app.mjs'), new Request(scope + 'v1/pull', {
    method: 'POST'
  })]) assert.equal(cacheable(request, scope), false);
  for(const path of SHELL.filter(x => x !== './')) assert.ok(readFileSync(new URL('../' + path, import.meta.url)).length);
}
);
test(
'English and Traditional Chinese expose the same user-visible messages',
() => {
  assert.deepEqual(Object.keys(messages.en).sort(), Object.keys(messages['zh-TW']).sort());
}
);
test(
'all executable modules parse; UI has no unsafe HTML or persisted token path',
() => {
  for(const name of readdirSync(new URL('../', import.meta.url)).filter(x => x.endsWith('.mjs'))) {
    const result = spawnSync(
    process.execPath,
    ['--check', new URL('../' + name, import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1')],
    {
      encoding: 'utf8'
    }
    );
    assert.equal(result.status, 0, result.stderr);
  }
  const ui = readFileSync(new URL('../app.mjs', import.meta.url), 'utf8');
  assert.equal(ui.includes('innerHTML'), false);
  assert.equal(ui.includes('localStorage'), false);
  assert.ok(ui.includes('aria-live'));
  assert.ok(ui.includes('selectionStart'));
}
);
