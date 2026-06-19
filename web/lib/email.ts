import { Resend } from 'resend'

const resend = new Resend(process.env.RESEND_API_KEY)
const FROM = 'NewsFlow <hello@newsflow.ink>'

export async function sendMagicLink(to: string, token: string): Promise<void> {
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000'
  const link = `${baseUrl}/activate?token=${token}`

  await resend.emails.send({
    from: FROM,
    to,
    subject: "You're in — NewsFlow access link",
    html: `
      <p style="font-family:Georgia,serif;font-size:16px;line-height:1.6;color:#1a1a1a;max-width:520px">
        Your access link is below. It expires in 7 days. Click to connect your Gmail
        and pick a delivery time.
      </p>
      <p style="margin:28px 0">
        <a href="${link}" style="font-family:Georgia,serif;font-size:16px;color:#6b1a0f;text-decoration:underline">
          Activate my account →
        </a>
      </p>
      <p style="font-family:'Courier New',monospace;font-size:11px;color:#888;letter-spacing:0.08em;text-transform:uppercase">
        If you didn't request this, ignore this email.
      </p>
    `,
    text: `Your access link:\n\n${link}\n\nExpires in 7 days. If you didn't request this, ignore this email.`,
  })
}

export async function sendAdminAlert(
  signup: { email: string; newsletter_picks: string[]; other_text: string }
): Promise<void> {
  const adminEmail = process.env.ADMIN_EMAIL ?? 'rushilmisc77@gmail.com'

  await resend.emails.send({
    from: FROM,
    to: adminEmail,
    subject: `[NewsFlow] New waitlist signup — ${signup.email}`,
    text: [
      `New waitlist signup requires manual review.`,
      ``,
      `Email: ${signup.email}`,
      `Newsletters: ${signup.newsletter_picks.join(', ') || '(none selected)'}`,
      `Other: ${signup.other_text || '(none)'}`,
    ].join('\n'),
  })
}
