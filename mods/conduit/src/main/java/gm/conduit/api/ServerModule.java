package gm.conduit.api;

/**
 * A piece of server code that can be loaded and replaced while the game runs. Everything it hooks goes
 * through its {@link ServerModuleContext}, so unloading removes it all without the module's help.
 */
public interface ServerModule {
	void enable(ServerModuleContext context);

	default void disable() {}
}
