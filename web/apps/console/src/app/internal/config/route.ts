import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    stripePriceIdStarter: process.env.STRIPE_PRICE_ID_STARTER ?? "",
    stripePriceIdGrowth: process.env.STRIPE_PRICE_ID_GROWTH ?? "",
    stripePriceIdScale: process.env.STRIPE_PRICE_ID_SCALE ?? "",
  });
}