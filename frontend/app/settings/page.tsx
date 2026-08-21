import { redirect } from "next/navigation";

/** Legacy link compatibility. Model management now lives in unified dispatch settings. */
export default function SettingsPage() {
  redirect("/?settings=dispatch");
}
