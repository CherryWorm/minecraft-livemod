package gm.conduit.modules;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.jar.JarEntry;
import java.util.jar.JarInputStream;

/** Loads one module from memory, so that releasing it lets its classes be garbage collected. */
final class ModuleClassLoader extends ClassLoader {
	private final Map<String, byte[]> entries = new HashMap<>();

	ModuleClassLoader(byte[] jar, ClassLoader parent) throws IOException {
		super(parent);
		try (JarInputStream input = new JarInputStream(new ByteArrayInputStream(jar))) {
			JarEntry entry;
			while ((entry = input.getNextJarEntry()) != null) {
				if (!entry.isDirectory()) {
					this.entries.put(entry.getName(), input.readAllBytes());
				}
			}
		}
	}

	@Override
	protected Class<?> findClass(String name) throws ClassNotFoundException {
		byte[] bytes = this.entries.get(name.replace('.', '/') + ".class");
		if (bytes == null) {
			throw new ClassNotFoundException(name);
		}
		return defineClass(name, bytes, 0, bytes.length);
	}

	@Override
	public InputStream getResourceAsStream(String name) {
		byte[] bytes = this.entries.get(name);
		return bytes != null ? new ByteArrayInputStream(bytes) : super.getResourceAsStream(name);
	}
}
