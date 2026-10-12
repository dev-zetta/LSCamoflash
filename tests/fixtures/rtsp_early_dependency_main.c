/* Link the early fixture as DT_NEEDED, independently of LD_PRELOAD ordering. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

int early_dependency_passed(void);

int main(void)
{
    const char *expected = getenv("RTSP_FIXTURE_EXPECT_PROFILE");
    assert(expected && early_dependency_passed());
    assert(!getenv("LSCAMOFLASH_RTSP_PROFILE"));
    if (*expected)
        assert(!getenv("LD_PRELOAD"));
    puts("SYNTHETIC-MAIN PASS");
    return 0;
}
