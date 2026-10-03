import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Voto em pauta | Eleições 2026",
  description: "Consulte candidaturas e propostas de governo com dados oficiais do TSE.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
