import * as keytar from 'keytar'

const SERVICE_NAME = 'DeepTutor'

export async function keytarGet(account: string): Promise<string | null> {
  try {
    return await keytar.getPassword(SERVICE_NAME, account)
  } catch (error) {
    console.error('keytar get error:', error)
    return null
  }
}

export async function keytarSet(account: string, password: string): Promise<boolean> {
  try {
    await keytar.setPassword(SERVICE_NAME, account, password)
    return true
  } catch (error) {
    console.error('keytar set error:', error)
    return false
  }
}

export async function keytarDelete(account: string): Promise<boolean> {
  try {
    await keytar.deletePassword(SERVICE_NAME, account)
    return true
  } catch (error) {
    console.error('keytar delete error:', error)
    return false
  }
}
