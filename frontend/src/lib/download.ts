/**
 * Hand a file the API produced to the browser as a download.
 *
 * The export endpoints sit behind the session cookie and the CSRF header, so a
 * plain `<a href>` to them would not carry what the request needs once the API
 * is on another origin. The page fetches the bytes with `apiFetchBlob` and this
 * saves them.
 */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // After the click has been handled; revoking synchronously can cancel the save.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
