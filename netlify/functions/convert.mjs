// ─────────────────────────────────────────────────────────────────────────────
// Excel-to-CSV Converter helper for KampusVibes Apps Script email gate.
//
// Accepts binary POST request, parses the first sheet to CSV, compresses it (gzip),
// and returns the base64-encoded compressed CSV string.
//
// Protected by the shared key:
//   POST /.netlify/functions/convert?key=<BLOCKLIST_READ_KEY>
// ─────────────────────────────────────────────────────────────────────────────
import XLSX from 'xlsx';
import zlib from 'zlib';

export default async (req) => {
  // 1. Verify shared key
  const key = new URL(req.url).searchParams.get('key');
  if (!process.env.BLOCKLIST_READ_KEY || key !== process.env.BLOCKLIST_READ_KEY) {
    return new Response('Forbidden', { status: 403 });
  }

  if (req.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  try {
    // 2. Read raw binary body bytes
    const arrayBuffer = await req.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    if (buffer.length === 0) {
      return new Response(JSON.stringify({ error: 'Empty payload body' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 3. Parse Excel using SheetJS
    const workbook = XLSX.read(buffer, { type: 'buffer' });
    if (!workbook.SheetNames || workbook.SheetNames.length === 0) {
      return new Response(JSON.stringify({ error: 'No worksheets found in file' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 4. Convert the first worksheet to CSV
    const firstSheetName = workbook.SheetNames[0];
    const worksheet = workbook.Sheets[firstSheetName];
    const csvContent = XLSX.utils.sheet_to_csv(worksheet);

    if (!csvContent || csvContent.trim().length === 0) {
      return new Response(JSON.stringify({ error: 'Parsed sheet is empty' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // 5. Compress CSV string using standard GZIP
    const gzipped = zlib.gzipSync(Buffer.from(csvContent, 'utf-8'));

    // 6. Return Base64-encoded gzipped data in JSON response
    const base64 = gzipped.toString('base64');

    return new Response(JSON.stringify({ base64 }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error('Conversion helper failed:', err);
    return new Response(JSON.stringify({ error: 'Conversion failed: ' + err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
