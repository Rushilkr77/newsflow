import nodemailer from 'nodemailer'

const transporter = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_APP_PASSWORD,
  },
})

export async function sendMagicLink(to: string, token: string): Promise<void> {
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000'
  const link = `${baseUrl}/activate?token=${token}`

  await transporter.sendMail({
    from: `"NewsFlow" <${process.env.SMTP_USER}>`,
    to,
    subject: "You're in — NewsFlow access link",
    text: [
      `Your access link is below. It expires in 7 days.`,
      `Click to connect your Gmail and pick a delivery time.`,
      ``,
      link,
      ``,
      `If you didn't request this, ignore this email.`,
    ].join('\n'),
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
  })
}

export async function sendAdminAlert(
  signup: { email: string; newsletter_picks: string[]; other_text: string }
): Promise<void> {
  const adminEmail = process.env.ADMIN_EMAIL ?? 'rushilkumar01@gmail.com'

  await transporter.sendMail({
    from: `"NewsFlow Waitlist" <${process.env.SMTP_USER}>`,
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
