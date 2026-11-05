import { redirect } from "next/navigation";
import { yourSettingsHome } from "@/components/next/settings/section";

export default function Page() {
  redirect(yourSettingsHome);
}
