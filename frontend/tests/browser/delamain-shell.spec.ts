import { expect, test } from '@playwright/test'

test('chat shell opens the vault panel and composer stays usable', async ({ page }) => {
  await page.goto('/')

  const messageInput = page.getByLabel('Message input')
  await expect(messageInput).toBeVisible()
  await messageInput.fill('my schedule')
  await expect(messageInput).toHaveValue('my schedule')

  await page.getByLabel('Vault panel').click()
  await expect(page.getByText(/vault index|nodes|Vault endpoints unavailable/i)).toBeVisible()

  const maintenanceTab = page.getByRole('button', { name: /Maint/i })
  await expect(maintenanceTab).toBeVisible()
  await maintenanceTab.click()
  await expect(page.getByText(/Vault endpoints unavailable|new structured folder/i)).toBeVisible()

  await page.getByLabel('Uploads panel').click()
  await expect(page.getByText('Uploads')).toBeVisible()
  await expect(page.getByText(/pending|No uploads in intake|Failed to load uploads/i)).toBeVisible()

  const modelRoute = page.getByLabel('Active model route')
  await expect(modelRoute).toBeVisible()
  await messageInput.fill('/model')
  await expect(messageInput).toHaveValue('/model')
})
