import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import styles from "./HomePage.module.css";

interface HealthResponse {
  status: string;
  version: string;
}

export function HomePage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthResponse>("/health"),
  });

  return (
    <main className={styles.container}>
      <h1>TriageAI</h1>
      <p>
        API status: {isPending && "checking..."}
        {isError && "unreachable"}
        {data && data.status}
      </p>
    </main>
  );
}
