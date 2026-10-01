/** An unknown path inside the shell. The header stays, so the user can get out. */
import { strings } from "../../i18n/strings";

export function NotFound() {
  return (
    <section>
      <h1>{strings.notFound.title}</h1>
      <p>{strings.notFound.body}</p>
    </section>
  );
}
