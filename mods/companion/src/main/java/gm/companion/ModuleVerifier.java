package gm.companion;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarInputStream;

/**
 * Decides whether a module may run on this computer. Only the broker holds the private key, so even a
 * compromised server can't push code here unless the broker signed it. The code scan repeats a check
 * the broker has already made, because this is the last line of defence on a friend's PC.
 */
final class ModuleVerifier {
	private static final Logger LOGGER = LoggerFactory.getLogger("Companion");
	private static final Path GENERATIONS = Path.of("config", "companion", "generations.json");
	private static final byte[] ED25519_X509_PREFIX = HexFormat.of().parseHex("302a300506032b6570032100");
	private static final List<String> FORBIDDEN = List.of(
			"java/io/File", "java/io/RandomAccessFile", "java/nio/file/", "java/net/", "java/lang/Runtime",
			"java/lang/ProcessBuilder", "java/lang/reflect/", "java/lang/ClassLoader",
			"sun/", "jdk/internal/", "org/lwjgl/", "net/minecraft/client/User", "java/lang/Thread");
	// Ordinary error handling, whose name happens to start with java/lang/Runtime.
	private static final String HARMLESS = "java/lang/RuntimeException";
	// Every lambda mentions MethodHandles$Lookup, so it's getting hold of a lookup that has to be refused.
	private static final Set<String> FORBIDDEN_NAMES = Set.of(
			"forName", "getDeclaredMethod", "loadLibrary", "lookup", "publicLookup", "privateLookupIn");

	private final PublicKey publicKey = readKey();
	private final boolean allowUnsigned = Boolean.getBoolean("companion.allowUnsigned");
	private JsonObject generations = readGenerations();

	/** Returns why a module is refused, or null if it may load. */
	String refusal(String moduleId, int generation, byte[] jar, String signature) {
		if (!this.allowUnsigned) {
			if (this.publicKey == null) {
				return "this companion has no signing key";
			}
			if (signature == null || signature.isEmpty() || !signatureValid(moduleId, generation, jar, signature)) {
				return "its signature isn't valid";
			}
			int newest = this.generations.has(moduleId) ? this.generations.get(moduleId).getAsInt() : -1;
			if (generation < newest) {
				return "it's older than a version already run here";
			}
		}
		String banned = scan(jar);
		if (banned != null) {
			return "it refers to " + banned;
		}
		return null;
	}

	void accepted(String moduleId, int generation) {
		this.generations.addProperty(moduleId, generation);
		try {
			Files.createDirectories(GENERATIONS.getParent());
			Files.writeString(GENERATIONS, new Gson().toJson(this.generations));
		} catch (IOException error) {
			LOGGER.warn("Couldn't save module versions", error);
		}
	}

	private boolean signatureValid(String moduleId, int generation, byte[] jar, String signature) {
		try {
			String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(jar));
			byte[] message = (moduleId + "\n" + generation + "\n" + digest).getBytes(StandardCharsets.UTF_8);
			Signature verifier = Signature.getInstance("Ed25519");
			verifier.initVerify(this.publicKey);
			verifier.update(message);
			return verifier.verify(Base64.getDecoder().decode(signature));
		} catch (GeneralSecurityException | IllegalArgumentException error) {
			LOGGER.warn("Couldn't check a module's signature", error);
			return false;
		}
	}

	/** Looks through every class's constant pool for names it must not use. Returns the first one found. */
	static String scan(byte[] jar) {
		try (JarInputStream input = new JarInputStream(new ByteArrayInputStream(jar))) {
			JarEntry entry;
			while ((entry = input.getNextJarEntry()) != null) {
				if (entry.getName().endsWith(".class")) {
					String banned = scanClass(input.readAllBytes());
					if (banned != null) {
						return banned;
					}
				}
			}
		} catch (IOException error) {
			return "a damaged jar";
		}
		return null;
	}

	private static String scanClass(byte[] bytes) throws IOException {
		try (DataInputStream data = new DataInputStream(new ByteArrayInputStream(bytes))) {
			data.readInt();
			data.readUnsignedShort();
			data.readUnsignedShort();
			int count = data.readUnsignedShort();
			for (int index = 1; index < count; index++) {
				int tag = data.readUnsignedByte();
				switch (tag) {
					case 1 -> {
						String text = data.readUTF().replace(HARMLESS, "");
						for (String forbidden : FORBIDDEN) {
							if (text.contains(forbidden)) {
								return forbidden;
							}
						}
						if (FORBIDDEN_NAMES.contains(text)) {
							return text;
						}
					}
					case 3, 4, 9, 10, 11, 12, 17, 18 -> data.readInt();
					case 5, 6 -> {
						data.readLong();
						index++;
					}
					case 7, 8, 16, 19, 20 -> data.readUnsignedShort();
					case 15 -> {
						data.readUnsignedByte();
						data.readUnsignedShort();
					}
					default -> throw new IOException("Unknown constant tag " + tag);
				}
			}
		}
		return null;
	}

	private static PublicKey readKey() {
		String encoded = System.getProperty("companion.publicKey");
		if (encoded == null) {
			try (InputStream input = ModuleVerifier.class.getResourceAsStream("/module_key.pub")) {
				if (input == null) {
					return null;
				}
				encoded = new String(input.readAllBytes(), StandardCharsets.UTF_8);
			} catch (IOException error) {
				return null;
			}
		}
		try {
			byte[] raw = Base64.getDecoder().decode(encoded.trim());
			byte[] der = raw;
			if (raw.length == 32) {
				der = new byte[ED25519_X509_PREFIX.length + raw.length];
				System.arraycopy(ED25519_X509_PREFIX, 0, der, 0, ED25519_X509_PREFIX.length);
				System.arraycopy(raw, 0, der, ED25519_X509_PREFIX.length, raw.length);
			}
			return KeyFactory.getInstance("Ed25519").generatePublic(new X509EncodedKeySpec(der));
		} catch (GeneralSecurityException | IllegalArgumentException error) {
			LOGGER.error("The companion's signing key is damaged", error);
			return null;
		}
	}

	private static JsonObject readGenerations() {
		try {
			if (Files.exists(GENERATIONS)) {
				return new Gson().fromJson(Files.readString(GENERATIONS), JsonObject.class);
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.warn("Couldn't read module versions", error);
		}
		return new JsonObject();
	}
}
