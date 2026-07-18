"use client";

import {Bell, Gauge, History, LayoutDashboard, Network, Search, Settings2, ShieldCheck} from "lucide-react";
import {motion} from "framer-motion";
import {useLocale, useTranslations} from "next-intl";
import {Link, usePathname, useRouter} from "@/i18n/navigation";
import type {AppLocale} from "@/i18n/routing";
import {cn} from "@/lib/ui";

const navItems = [
  {key: "dashboard", href: "/", icon: LayoutDashboard},
  {key: "history", href: "/history", icon: History},
  {key: "workflow", href: "/workflow", icon: Network},
  {key: "monitoring", href: "/monitoring", icon: Gauge},
  {key: "settings", href: "/settings", icon: Settings2},
] as const;

function LanguageSwitcher() {
  const locale = useLocale() as AppLocale;
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("Accessibility");

  function changeLocale(nextLocale: AppLocale) {
    if (nextLocale !== locale) router.replace(pathname, {locale: nextLocale});
  }

  return (
    <div className="flex h-10 items-center rounded-xl bg-slate-50 p-1 ring-1 ring-slate-200" aria-label={t("languageSwitcher")}>
      {(["vi", "en"] as const).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => changeLocale(item)}
          aria-pressed={locale === item}
          className={cn(
            "h-8 rounded-lg px-2.5 text-xs font-semibold uppercase transition",
            locale === item ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:text-slate-900",
          )}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

export function AppShell({children}: {children: React.ReactNode}) {
  const pathname = usePathname();
  const navigation = useTranslations("Navigation");
  const common = useTranslations("Common");
  const accessibility = useTranslations("Accessibility");

  const isActive = (href: string) => href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <header className="fixed inset-x-0 top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6 lg:px-8">
          <Link href="/" className="flex shrink-0 items-center gap-3">
            <span className="grid size-9 place-items-center rounded-xl bg-blue-600 text-white">
              <ShieldCheck className="size-5" />
            </span>
            <span className="hidden text-base font-semibold text-slate-950 sm:block">AML-Investigator</span>
          </Link>

          <nav className="mx-auto hidden items-center gap-1 rounded-xl bg-slate-50 p-1 ring-1 ring-slate-200 xl:flex" aria-label={accessibility("mainNavigation")}>
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  className={cn(
                    "inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition",
                    active ? "bg-white text-blue-700 shadow-sm" : "text-slate-600 hover:bg-white hover:text-slate-950",
                  )}
                >
                  <Icon className="size-4" />
                  {navigation(item.key)}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <div className="hidden h-10 w-56 items-center gap-2 rounded-xl bg-slate-50 px-3 text-sm text-slate-600 ring-1 ring-slate-200 lg:flex">
              <Search className="size-4" />
              <input className="w-full bg-transparent outline-none placeholder:text-slate-500" placeholder={common("globalSearch")} aria-label={common("globalSearch")} />
            </div>
            <LanguageSwitcher />
            <button type="button" className="hidden size-10 place-items-center rounded-xl bg-white text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-50 hover:text-slate-950 sm:grid" aria-label={accessibility("notifications")}>
              <Bell className="size-5" />
            </button>
            <button type="button" className="hidden size-10 place-items-center rounded-xl bg-blue-100 text-sm font-semibold text-blue-700 ring-1 ring-blue-200 sm:grid" aria-label={accessibility("userAvatar")}>
              AI
            </button>
          </div>
        </div>

        <nav className="flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 xl:hidden" aria-label={accessibility("mobileNavigation")}>
          {navItems.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className={cn(
                "shrink-0 rounded-xl px-3 py-2 text-sm font-medium transition",
                isActive(item.href) ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-700",
              )}
            >
              {navigation(item.key)}
            </Link>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 pb-10 pt-32 sm:px-6 xl:px-8 xl:pt-24">
        <motion.div
          key={pathname}
          initial={{opacity: 0, y: 10}}
          animate={{opacity: 1, y: 0}}
          transition={{duration: 0.18, ease: "easeOut"}}
        >
          {children}
        </motion.div>
      </main>
    </div>
  );
}
