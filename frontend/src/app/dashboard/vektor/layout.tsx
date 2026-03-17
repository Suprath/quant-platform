import './terminal.css';

export default function AlphaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="alpha-terminal bg-black text-white min-h-screen overflow-hidden">
      {children}
    </div>
  );
}
