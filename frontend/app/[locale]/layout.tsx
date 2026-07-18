import type {Metadata} from "next";
import {hasLocale, NextIntlClientProvider} from "next-intl";
import {getTranslations, setRequestLocale} from "next-intl/server";
import {notFound} from "next/navigation";
import "@xyflow/react/dist/style.css";
import "../globals.css";
import {AppShell} from "@/components/app-shell";
import {routing} from "@/i18n/routing";

type Props = {
  children: React.ReactNode;
  params: Promise<{locale: string}>;
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({locale}));
}

export async function generateMetadata({params}: Props): Promise<Metadata> {
  const {locale} = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({locale, namespace: "Metadata"});

  return {
    title: t("title"),
    description: t("description"),
  };
}

export default async function LocaleLayout({children, params}: Props) {
  const {locale} = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);

  return (
    <html lang={locale} className="h-full antialiased">
      <body className="min-h-full">
        <NextIntlClientProvider>
          <AppShell>{children}</AppShell>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
