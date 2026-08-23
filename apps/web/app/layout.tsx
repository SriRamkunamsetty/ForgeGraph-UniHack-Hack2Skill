import "./globals.css";

export const metadata = {
  title: "ForgeGraph | Industrial Product Intelligence",
  description: "Evidence-backed product truth for industrial commerce",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
