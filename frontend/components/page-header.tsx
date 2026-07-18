export function PageHeader({title, subtitle}: {title: string; subtitle: string}) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-3xl font-semibold tracking-normal text-slate-950">{title}</h1>
      <p className="max-w-3xl text-base leading-7 text-slate-600">{subtitle}</p>
    </div>
  );
}
