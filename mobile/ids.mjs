/** Synchronous RFC 4122 UUID5 for the protocol's deterministic identities. */
const URL_NAMESPACE = '6ba7b8119dad11d180b400c04fd430c8';
export function uuid5Name(name) {
  const namespace = Uint8Array.from(URL_NAMESPACE.match(/../g), part => parseInt(part, 16));
  const text = new TextEncoder().encode(name),
  input = new Uint8Array(namespace.length + text.length);
  input.set(namespace);
  input.set(text, namespace.length);
  const length = input.length,
  size = Math.ceil((length + 9) / 64) * 64,
  bytes = new Uint8Array(size);
  bytes.set(input);
  bytes[length] = 128;
  const view = new DataView(bytes.buffer);
  view.setUint32(size - 4, length * 8);
  let h0 = 0x67452301,
  h1 = 0xefcdab89,
  h2 = 0x98badcfe,
  h3 = 0x10325476,
  h4 = 0xc3d2e1f0;
  const rotate =(x, n) =>(x << n) |(x >>>(32 - n)),
  words = new Int32Array(80);
  for(let offset = 0; offset < size; offset += 64) {
    for(let i = 0; i < 16; i++) words[i] = view.getInt32(offset + i * 4);
    for(let i = 16; i < 80; i++) words[i] = rotate(words[i - 3] ^ words[i - 8] ^ words[i - 14] ^ words[i - 16],
    1);
    let a = h0,
    b = h1,
    c = h2,
    d = h3,
    e = h4;
    for(let i = 0; i < 80; i++) {
      const f = i < 20 ?(b & c) |(~ b & d): i < 40 ? b ^ c ^ d: i < 60 ?(b & c) |(b & d) |(c & d): b ^ c ^ d;
      const k = i < 20 ? 0x5a827999: i < 40 ? 0x6ed9eba1: i < 60 ? 0x8f1bbcdc: 0xca62c1d6;
      const temp =(rotate(a, 5) + f + e + k + words[i]) | 0;
      e = d;
      d = c;
      c = rotate(b, 30);
      b = a;
      a = temp;
    }
    h0 =(h0 + a) | 0;
    h1 =(h1 + b) | 0;
    h2 =(h2 + c) | 0;
    h3 =(h3 + d) | 0;
    h4 =(h4 + e) | 0;
  }
  const output = new Uint8Array(16),
  out = new DataView(output.buffer);
  [h0, h1, h2, h3].forEach((word, i) => out.setInt32(i * 4, word));
  output[6] =(output[6] & 15) | 80;
  output[8] =(output[8] & 63) | 128;
  const hex =[...output].map(x => x.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export const asciiJSON = value => JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => '\\u' + char.charCodeAt(0).toString(16).padStart(4,
'0'));
export const contentId =(scope, feature, key) => uuid5Name('paperfact:research-content:' + asciiJSON([scope.kind,
scope.id, feature, key]));
