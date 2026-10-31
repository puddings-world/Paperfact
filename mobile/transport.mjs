import {
  closed,
  identifier,
  integer,
  requireThat,
  validateEvent
} from './domain.mjs';
import {parsePositionJSON} from './position-json.mjs';
import {sourceFileId,validateArtifact,validateOriginalSource} from './artifacts.mjs';
export const CHUNK = 256 * 1024;
export class TransportError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}
export class HttpTransport {
  constructor(origin, {
    fetch = globalThis.fetch
  } = {}) {
    const url = new URL(origin);
    requireThat(
    ! url.username && ! url.password && ! url.search && ! url.hash && url.pathname === '/',
    'invalid_origin'
    );
    requireThat(
    url.protocol === 'https:' ||(url.protocol === 'http:' &&['127.0.0.1', '[::1]'].includes(url.hostname)),
    'invalid_origin'
    );
    this.origin = url.origin;
    this.fetch = fetch;
  }
  async post(route, body, token, signal) {
    requireThat(
    typeof token === 'string' && token.length > 0 && token.length <= 4096 && ! /[\r\n]/.test(token),
    'invalid_session'
    );
    const data = JSON.stringify(body);
    requireThat(new TextEncoder().encode(data).length <= 512 * 1024, 'request_too_large');
    let response;
    try {
      const request = this.fetch;
      response = await request(
      this.origin + route,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: data,
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
        signal
      }
      );
    } catch {
      throw new TransportError(signal?.aborted ? 'cancelled': 'connection_failed');
    }
    if(! response.ok) {
      await response.body?.cancel();
      throw new TransportError(({
        401: 'session_denied',
        403: 'session_denied',
        404: 'unsupported_service',
        409: 'file_unavailable',
        413: 'quota_exceeded',
        503: 'unsupported_service'
      })[response.status] ?? 'request_rejected');
    }
    requireThat(response.headers.get('content-type')?.split(';')[0] === 'application/json', 'invalid_response');
    const reader = response.body.getReader(),
    parts =[];
    let size = 0;
    try {
      while(true) {
        const {
          done,
          value
        } = await reader.read();
        if(done) break;
        size += value.length;
        requireThat(size <= 2 * 1024 * 1024, 'response_too_large');
        parts.push(value);
      }
    } catch(error) {
      await reader.cancel();
      throw error;
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for(const part of parts) {
      bytes.set(part, offset);
      offset += part.length;
    }
    try {
      return parsePositionJSON(new TextDecoder('utf-8', {
        fatal: true
      }).decode(bytes));
    } catch {
      throw new TransportError('invalid_response');
    }
  }
  async session_info(token, signal) {
    const value = await this.post('/v1/session/info', {}, token, signal);
    closed(value, ['workspace_id', 'device_id']);
    identifier(value.workspace_id);
    identifier(value.device_id);
    return value;
  }
  async push(token, operation, signal) {
    const event = await this.post('/v1/push', {
      operation
    }, token, signal);
    return validateEvent(event, operation.workspace_id);
  }
  async pull(token, after = 0, limit = 100, signal) {
    integer(after);
    requireThat(Number.isInteger(limit) && limit >= 1 && limit <= 1000);
    const events = await this.post('/v1/pull', {
      after,
      limit
    }, token, signal);
    requireThat(Array.isArray(events) && events.length <= limit, 'invalid_response');
    return events;
  }
  async blob_read(token, sha256, size, offset, limit = CHUNK, signal) {
    requireThat(/^[0-9a-f]{64}$/.test(sha256));
    integer(size);
    integer(offset);
    requireThat(offset <= size && Number.isInteger(limit) && limit >= 1 && limit <= CHUNK);
    const value = await this.post('/v1/blobs/read', {
      sha256,
      size,
      offset,
      limit
    }, token, signal);
    closed(value, ['data']);
    requireThat(typeof value.data === 'string' && value.data.length <= 4 * Math.ceil(CHUNK / 3), 'invalid_response');
    let raw;
    try {
      raw = atob(value.data);
    } catch {
      throw new TransportError('invalid_response');
    }
    requireThat(btoa(raw) === value.data && raw.length === Math.min(limit, size - offset), 'invalid_response');
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  }
  async uploadOriginalBody(token,payload,bytes,signal) {
    validateArtifact(payload,sourceFileId(payload.paper_id,payload.slot));
    validateOriginalSource(bytes,payload);
    requireThat(bytes.length===payload.body.size,'invalid_original_body');
    const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))]
      .map(value=>value.toString(16).padStart(2,'0')).join('');
    requireThat(hash===payload.body.sha256,'invalid_original_body');
    const manifest={sha256:hash,size:bytes.length};
    const started=await this.post('/v1/blobs/begin',manifest,token,signal);
    closed(started,['upload_id','sha256','size','offset','complete']);integer(started.offset);
    requireThat(started.sha256===hash && started.size===bytes.length && typeof started.complete==='boolean' &&
      started.offset<=bytes.length,'invalid_response');
    if(started.complete) {
      requireThat(started.upload_id===null && started.offset===bytes.length,'invalid_response');return;
    }
    requireThat(typeof started.upload_id==='string' && /^[A-Za-z0-9_-]{32,64}$/.test(started.upload_id),'invalid_response');
    if(started.offset<bytes.length) {
      const result=await this.post('/v1/blobs/append',{upload_id:started.upload_id,offset:started.offset,
        data:btoa(String.fromCharCode(...bytes.subarray(started.offset)))},token,signal);
      closed(result,['offset']);requireThat(result.offset===bytes.length,'invalid_response');
    }
    const committed=await this.post('/v1/blobs/commit',{upload_id:started.upload_id},token,signal);
    closed(committed,['sha256','size','complete']);
    requireThat(committed.complete===true && committed.sha256===hash && committed.size===bytes.length,'invalid_response');
  }
}
